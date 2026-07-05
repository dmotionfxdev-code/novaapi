# Migration Extension Fix Report — postgis / pgcrypto on Shared-Hosting PostgreSQL

**Trigger**: production deployment failed during `alembic upgrade head` with:
```
1. postgis.control not found
2. pgcrypto.control not found
```

**Scope of this report**: trace both extensions' actual usage across every migration, every SQLAlchemy model, and all runtime code; determine whether either is truly required; patch `0000_baseline.py` if not. No other migration, model, or business logic was touched.

---

## 1. What `0000_baseline.py` Did (Before This Fix)

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # gen_random_uuid()
    for schema in db_schemas.ALL:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
```

`CREATE EXTENSION IF NOT EXISTS x` still requires `x`'s `.control` file to be physically present on the PostgreSQL server's filesystem — `IF NOT EXISTS` only guards against the extension being *already created*, not against it being *unavailable to create*. When the control file is missing (the common case on shared/managed PostgreSQL hosting, where contrib extensions must be installed at the OS/package level by the DBA, not by an ordinary database user), PostgreSQL raises a hard error, and — because this runs inside Alembic's single per-migration transaction — that error poisons the entire transaction, aborting the whole migration run, including the `CREATE SCHEMA` statements that follow and every subsequent migration (`0001` through `0016`).

## 2. Dependency Trace — Is `postgis` Actually Required?

Traced exhaustively across `migrations/versions/*.py`, every `src/georisk/contexts/*/infrastructure/models.py`, and all runtime code. **No.**

- **Every migration's geometry-bearing column is plain JSONB**, not PostGIS's `geometry`/`geography` type:
  ```
  migrations/versions/0008_geospatial.py:35:  sa.Column("geometry", postgresql.JSONB, nullable=False)
  ```
  Confirmed the *only* `geometry`-named column in all 17 migrations, and it is JSONB.
- **`contexts/geospatial/infrastructure/models.py`** (the SQLAlchemy ORM layer) declares `geometry: Mapped[dict] = mapped_column(JSONB, nullable=False)` — its own module docstring states this explicitly: *"geometry/bbox/centroid are stored as plain JSONB, not native PostGIS geometry columns... migration to native geometry + GiST indexing is a deferred infrastructure task, not a Sprint 7 requirement."* This was a deliberate Sprint 7 architecture decision, not an oversight.
- **The `Geometry` symbol used in `contexts/geospatial/infrastructure/mappers.py` and `application/handlers.py`** is the codebase's *own* pure-Python value object (`contexts.geospatial.domain.value_objects.Geometry`, a validated-GeoJSON dataclass), confirmed by reading each file's import block — not `geoalchemy2.Geometry`.
- **`geoalchemy2==0.16.0`** is listed in `pyproject.toml` but grepping every file under `src/` for `geoalchemy2`/`from geoalchemy` returns zero hits outside auto-generated `.egg-info` metadata (which just mirrors the dependency list). It has never been imported by any actual module.
- **No `ST_*` PostGIS function call appears anywhere** in migrations or `src/` (grepped for `ST_[A-Za-z]+\(` case-sensitively and case-insensitively).

**Conclusion**: `postgis` is entirely vestigial — declared in Sprint 0's baseline as anticipatory scaffolding, never actually depended on by any of Sprints 1-14's real implementation.

## 3. Dependency Trace — Is `pgcrypto` Actually Required?

Traced with equal rigor. **No.**

- The only justification ever given for enabling it was the inline comment `# gen_random_uuid()` on that exact line.
- **`gen_random_uuid()` is never called anywhere** — grepped every migration file and every model file for the literal string; zero hits beyond the comment itself.
- **Every ID in this platform is generated application-side.** `TypedId.new()` (`shared_kernel/ids.py`) — the base class every concrete ID type (`TenantId`, `AssessmentId`, `DatasetId`, `AcquisitionJobId`, ...) subclasses — returns `cls(value=uuid.uuid4())`. This is pure Python, no database round-trip, no `gen_random_uuid()`.
- **No column anywhere declares a database-side UUID default.** Grepped every migration for `server_default` combined with `uuid`/`random`/`gen_`: zero matches. Every primary-key column is populated by the application before the `INSERT`, not by a column default.
- **No other pgcrypto function** (`crypt()`, `pgp_sym_encrypt()`, `digest()`, `hmac()`, `gen_salt()`) appears anywhere — password hashing in this platform uses Argon2id via the `argon2-cffi` Python library (`contexts/identity/infrastructure/security.py`), entirely independent of any PostgreSQL extension.

**Conclusion**: `pgcrypto` is equally vestigial — its sole stated purpose is never exercised by any code path.

## 4. Can Both Be Made Optional? — Yes, Verified

Since neither is used, the correct fix is to make `CREATE EXTENSION` best-effort: attempt it (so a host that *does* have them gets them created, harmlessly, for any future sprint that might want one), but never let a failure here abort the migration chain.

### The Patch

```python
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
            extension_name, getattr(exc, "orig", exc),
        )


def upgrade() -> None:
    for extension_name in _OPTIONAL_EXTENSIONS:
        _try_create_extension(extension_name)
    for schema in db_schemas.ALL:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
```

**Why the `SAVEPOINT` (`connection.begin_nested()`) matters**: without it, catching the Python exception is not enough — PostgreSQL aborts the *entire* enclosing transaction on any statement error, so the subsequent `CREATE SCHEMA` statements (running in that same Alembic-managed transaction) would also fail even though the `try/except` "handled" the extension error in Python. `begin_nested()` issues a `SAVEPOINT` before the risky statement; on failure, SQLAlchemy automatically issues `ROLLBACK TO SAVEPOINT`, undoing only that nested portion and leaving the outer transaction — and every statement after it — able to proceed normally.

`downgrade()` needed no change: `DROP EXTENSION IF EXISTS x` checks PostgreSQL's `pg_extension` catalog (was it ever actually created?), not the `.control` file, so it already no-ops safely whether or not `upgrade()` skipped that extension.

## 5. Verification

Reproduced the **exact** reported production failure first, against a real PostgreSQL build genuinely missing both `.control` files (confirmed: only `plpgsql`/`vector` control files present, no `postgis`/`pgcrypto`) — not simulated or guessed:

```
sqlalchemy.exc.DBAPIError: (sqlalchemy.dialects.postgresql.asyncpg.Error)
<class 'asyncpg.exceptions.FeatureNotSupportedError'>: extension "postgis" is not available
DETAIL:  Could not open extension control file ".../postgis.control": No such file or directory.
```
This confirmed both the exact exception class (`sqlalchemy.exc.DBAPIError`, wrapping `asyncpg.exceptions.FeatureNotSupportedError`) and that the un-patched migration genuinely fails here — matching the user's report exactly.

**After the patch, against the same PostgreSQL build**:
```
WARNI [alembic.runtime.migration] Skipping optional extension 'postgis' — not available on this PostgreSQL server ...
WARNI [alembic.runtime.migration] Skipping optional extension 'pgcrypto' — not available on this PostgreSQL server ...
INFO  [alembic.runtime.migration] Running upgrade  -> 0000_baseline, ...
INFO  [alembic.runtime.migration] Running upgrade 0000_baseline -> 0001_identity_and_outbox, ...
... (all 17 migrations, 0000 -> 0016_remote_sensing, complete successfully) ...
```

Confirmed via direct query after migration: all 10 logical schemas created (`analysis`, `assessment`, `audit`, `data_acquisition`, `geospatial`, `identity`, `notification`, `prediction`, `reporting`, `validation`), `data_acquisition` schema's 5 tables present, and `pg_extension` shows only PostgreSQL's built-in `plpgsql` — no `postgis`, no `pgcrypto` — proving the platform is fully functional with neither.

**Additional checks, all passing**:
- Full downgrade (`alembic downgrade base`) → re-upgrade (`alembic upgrade head`) round-trip succeeds cleanly.
- Full test suite: **491 passed, 1 skipped**, zero regressions (identical to the pre-patch baseline — this change touches only extension-creation error handling, nothing functional).
- `ruff check .`, `mypy src/`, `lint-imports` — all clean.

## 6. Scope Discipline

This fix touches exactly one file (`migrations/versions/0000_baseline.py`) and changes exactly one behavior: extension creation is best-effort instead of hard-required. No other migration, model, entity, handler, or route was modified. No new features, no formula changes, no architectural changes.

## 7. Deployment Note

This fix means the platform can now migrate successfully on **any** PostgreSQL instance, including shared/managed hosting with no superuser-installed contrib extensions — exactly the class of environment `novaapi.novarex.co.tz` runs on. `CPANEL_DEPLOYMENT_GUIDE.md` §1 has been updated to state this plainly rather than the previous (incorrect, since disproven by this exact production failure) assumption that cPanel-hosted Postgres "typically already permits" these extensions.
