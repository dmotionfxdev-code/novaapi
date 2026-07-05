"""Baseline: enable required extensions and create logical schemas.

Revision ID: 0000_baseline
Revises:
Create Date: 2026-01-01 00:00:00

--- postgis/pgcrypto are OPTIONAL, not required (patched post-v1.1) ---

Production deployment to shared PostgreSQL hosting (no superuser access,
`CREATE EXTENSION` unavailable for extensions whose `.control` file isn't
installed on the server) failed here with:
    extension "postgis" is not available
    DETAIL: Could not open extension control file ".../postgis.control"
and the identical error for "pgcrypto". Traced before patching, not
guessed — neither extension is actually used by any migration, model, or
runtime code in this platform:

- `postgis`: every geometry column in this codebase (`geospatial.aoi.
  geometry`, `0008_geospatial.py`) is plain ``postgresql.JSONB``, storing
  a validated GeoJSON dict via the codebase's own pure-Python `Geometry`
  value object (`contexts.geospatial.domain.value_objects.Geometry`) —
  never PostGIS's `geometry`/`geography` SQL type. No migration or model
  anywhere declares a PostGIS column type; no runtime code calls any
  `ST_*` function. `geoalchemy2` is listed in `pyproject.toml` but is
  never imported by any file under `src/` — a Sprint 0 anticipatory
  dependency Sprint 7 explicitly decided not to use (see
  `contexts/geospatial/infrastructure/models.py`'s own module docstring:
  "geometry/bbox/centroid are stored as plain JSONB, not native PostGIS
  geometry columns... migration to native geometry + GiST indexing is a
  deferred infrastructure task, not a Sprint 7 requirement").
- `pgcrypto`: the only reason it was ever enabled was the inline comment
  on this line, "gen_random_uuid()" — grepping every migration and every
  model in this platform confirms that function is never actually called;
  every ID (`TenantId`, `AssessmentId`, `DatasetId`, ...) is generated
  application-side via `TypedId.new()` -> `uuid.uuid4()`
  (`shared_kernel/ids.py`), never a database-side default. No column
  anywhere declares `server_default=text("gen_random_uuid()")` or
  equivalent.

Both are therefore made **best-effort**: if the server has them
available, they're created (harmless, and forward-compatible with any
future sprint that genuinely wants one); if not, migration continues
without them rather than aborting the entire chain over an extension
nothing depends on. Each attempt runs in its own SAVEPOINT
(`connection.begin_nested()`) so a failure here cannot poison the
transaction the subsequent `CREATE SCHEMA` statements run in — verified
by reproducing the exact production failure against a real PostgreSQL
build with neither extension's control file installed, confirming
`CREATE SCHEMA` still succeeds afterward.
"""
import logging
from typing import Sequence, Union

from alembic import op
from sqlalchemy.exc import DBAPIError

from georisk.db import schemas as db_schemas

revision: str = "0000_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# Neither is required by this platform (see module docstring above) —
# best-effort only, never a hard dependency of the migration chain.
_OPTIONAL_EXTENSIONS: tuple[str, ...] = ("postgis", "pgcrypto")


def _try_create_extension(extension_name: str) -> None:
    connection = op.get_bind()
    try:
        with connection.begin_nested():  # SAVEPOINT: isolates the failure
            connection.exec_driver_sql(f"CREATE EXTENSION IF NOT EXISTS {extension_name}")
    except DBAPIError as exc:
        logger.warning(
            "Skipping optional extension %r — not available on this "
            "PostgreSQL server (%s). Not required by any current "
            "migration, model, or runtime code in this platform.",
            extension_name,
            getattr(exc, "orig", exc),
        )


def upgrade() -> None:
    for extension_name in _OPTIONAL_EXTENSIONS:
        _try_create_extension(extension_name)

    # SECURITY NOTE (Sprint 0 Review finding #7 / Remediation #7): this
    # f-string interpolation is safe ONLY because `schema` is drawn from
    # `db_schemas.ALL`, a hardcoded, developer-controlled tuple in this same
    # repository — never from request/tenant input. Roadmap Sprint 11's
    # schema-per-tenant mode will need to CREATE SCHEMA dynamically per
    # tenant; that code MUST NOT copy this pattern with a tenant-supplied
    # value substituted in without strict allowlist/format validation first
    # (e.g. deriving the schema name from a UUID, never from free text).
    # See CONTRIBUTING.md, "The one Sprint 0 landmine to know about".
    for schema in db_schemas.ALL:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")


def downgrade() -> None:
    for schema in db_schemas.ALL:
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    # IF EXISTS here checks pg_extension (was it ever actually created?),
    # not the control file — safe no-op if `upgrade()` skipped either one.
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute("DROP EXTENSION IF EXISTS postgis")
