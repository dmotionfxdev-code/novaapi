"""Real-database fixtures for integration tests.

Each test runs inside its own transaction that's rolled back at teardown
(Implementation Bootstrap §14's stated design, implemented for real here)
— tests never see each other's data, and there's no need to re-migrate or
truncate between tests.

``db_engine`` is function-scoped, not session-scoped, deliberately: an
async SQLAlchemy engine's connections are bound to the event loop they were
created in, and pytest-asyncio gives each test function its own event loop
by default. A session-scoped engine created in test 1's loop raises
"another operation is in progress" / "Event loop is closed" the moment
test 2 (a different loop) tries to use it — caught by actually running the
suite against real Postgres during Sprint 1 validation, not assumed safe
from the pattern looking reasonable in isolation. The extra per-test
connect/dispose cost is negligible next to what it prevents.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from georisk.db.session import Database

DATABASE_URL = os.environ.get("DATABASE_URL")


@pytest_asyncio.fixture
async def db_engine():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")

    engine = create_async_engine(DATABASE_URL)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:  # noqa: ANN001
    connection = await db_engine.connect()
    transaction = await connection.begin()
    session_factory = async_sessionmaker(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    session = session_factory()

    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def real_database() -> AsyncIterator[Database]:
    """A genuine, independently-connecting :class:`Database` — for the one
    handler (``RegisterTenantHandler``) that opens its own sessions rather
    than accepting one (see its module docstring). This means its writes
    are NOT covered by ``db_session``'s rollback-per-test isolation; tests
    using this fixture generate unique tenant names/emails per run instead,
    which is sufficient given the test database itself is ephemeral.
    """
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    db = Database(DATABASE_URL)
    yield db
    await db.dispose()
