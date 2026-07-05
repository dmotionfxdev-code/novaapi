"""Database engine/session lifecycle for both the API and Celery workers.

Two consumers, two lifecycles, one mechanism:

* **FastAPI** — a :class:`Database` instance is created once per app inside
  ``create_app()``'s lifespan and attached to ``app.state.db``. Each
  ``create_app()`` call therefore owns a genuinely independent engine, which
  is what makes two isolated app instances in the same test process actually
  isolated (Sprint 0 Review finding #14 / Remediation #14 — the original
  draft used a module-level global here, which silently defeated the
  app-factory's own test-isolation goal).

* **Celery workers** — a long-lived process with no per-request lifecycle to
  hang a dependency off. A single module-level :class:`Database` is
  initialized once at worker-process start (via Celery's
  ``worker_process_init`` signal, wired in ``celery_app/app.py``) and reused
  for the life of the worker process. This is the pattern Sprint 0 Review
  finding #4 / Remediation #4 flagged as missing entirely.

Read/write seam (finding #27 / Remediation #27): ``get_session()`` and
``get_read_session()`` both point at the same engine today. Routing the read
path to a replica (Infrastructure Architecture §21) is an additive change to
one function's implementation, not a refactor of every call site, because
the seam already exists.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class Database:
    """Owns one engine and its session factories. One instance per FastAPI
    app; one instance per Celery worker process. Never a bare module global.
    """

    def __init__(self, database_url: str, pool_size: int = 10) -> None:
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            pool_size=pool_size,
            pool_pre_ping=True,
        )
        # Same engine for both factories today — the split exists so a
        # future read-replica engine can be substituted into
        # `read_session_factory` alone (Infrastructure Architecture §21).
        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )
        self.read_session_factory: async_sessionmaker[AsyncSession] = self.session_factory

    async def dispose(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """One session per call, matching the one-transaction-per-command
        rule (Application Layer §9). Used directly by Celery tasks; wrapped
        by a FastAPI dependency for API request handlers.
        """
        async with self.session_factory() as session:
            yield session

    @asynccontextmanager
    async def read_session(self) -> AsyncIterator[AsyncSession]:
        async with self.read_session_factory() as session:
            yield session


# --- FastAPI dependencies -------------------------------------------------


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: ``Depends(get_session)``. Reads the app-scoped
    :class:`Database` from ``request.app.state.db`` — never a module global.
    """
    db: Database = request.app.state.db
    async with db.session() as session:
        yield session


async def get_read_session(request: Request) -> AsyncIterator[AsyncSession]:
    db: Database = request.app.state.db
    async with db.read_session() as session:
        yield session


def get_database(request: Request) -> Database:
    """FastAPI dependency for the rare route that needs the whole
    :class:`Database` rather than a single request-scoped session — e.g.
    ``WorkflowEngine`` (Roadmap Sprint 3), which opens several sequential
    transactions of its own as it dispatches a cascade of stage commands.
    """
    return request.app.state.db


# --- Celery worker session ------------------------------------------------

_worker_db: Database | None = None


def init_worker_database(database_url: str, pool_size: int = 5) -> None:
    """Called once from Celery's ``worker_process_init`` signal
    (``celery_app/app.py``) — establishes the single :class:`Database`
    instance a worker process reuses for every task it executes.
    """
    global _worker_db
    _worker_db = Database(database_url=database_url, pool_size=pool_size)


@asynccontextmanager
async def get_worker_session() -> AsyncIterator[AsyncSession]:
    """Session-acquisition pattern for use inside a Celery task, e.g.::

        class ComputeStageJob(PlatformTask):
            async def run(self, ...):
                async with get_worker_session() as session:
                    ...

    Raises ``RuntimeError`` if called before ``init_worker_database`` has
    run — a loud failure, not a silent ``None`` dereference, if a task is
    ever invoked outside a properly initialized worker process (e.g. in a
    unit test that forgot to set up the worker database fixture).
    """
    if _worker_db is None:
        raise RuntimeError(
            "init_worker_database() has not been called — are you calling "
            "get_worker_session() outside a Celery worker process?"
        )
    async with _worker_db.session() as session:
        yield session
