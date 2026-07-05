"""Alembic environment.

Single linear revision history for every logical schema (Architecture
Redesign §12) — no per-context migration trees.

Sprint 0 Review finding #16 / Remediation #16: the previous draft of this
file defined an ``include_schemas()`` helper that was never actually wired
into Alembic's configuration — dead code that implied schema filtering was
active when it wasn't. This version wires it into ``include_name``
correctly: only the platform's ten logical schemas (plus the default
``None``/unqualified case Alembic needs internally) are considered when
comparing metadata against the live database, so a stray schema created by
some other process is never mistaken for something this migration history
should manage.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from georisk.contexts.analysis.infrastructure import models as _analysis_models  # noqa: F401,E402
from georisk.contexts.assessment.infrastructure import (
    models as _assessment_models,  # noqa: F401,E402
)
from georisk.contexts.identity.infrastructure import models as _identity_models  # noqa: F401,E402
from georisk.contexts.validation.infrastructure import (
    models as _validation_models,  # noqa: F401,E402
)

# Import every context's models here as they're added, so Base.metadata is
# complete before autogenerate runs.
from georisk.db import idempotency_models as _idempotency_models  # noqa: F401,E402
from georisk.db import outbox_models as _outbox_models  # noqa: F401,E402
from georisk.db import schemas as db_schemas
from georisk.db.base import Base
from georisk.settings import get_settings

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_TARGET_SCHEMAS = set(db_schemas.ALL)


def include_name(name: str | None, type_: str, parent_names: dict[str, str]) -> bool:
    """Scope Alembic's autogenerate comparison to schemas this platform
    actually owns. Wired into both offline and online configuration below —
    see this module's docstring for why this replaces the previous
    unwired helper.
    """
    if type_ == "schema":
        return name in _TARGET_SCHEMAS or name is None
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
        version_table_schema=None,  # alembic_version stays in the default
        # (public) schema, explicitly, rather than inheriting whatever the
        # connection's search_path happens to resolve to.
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        version_table_schema=None,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        {"sqlalchemy.url": get_settings().database_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
