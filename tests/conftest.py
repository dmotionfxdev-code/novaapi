"""Shared pytest fixtures.

Uses ``fastapi.testclient.TestClient`` as a context manager rather than a
bare ``httpx.AsyncClient`` + ``ASGITransport`` — the latter does not run the
app's lifespan (startup/shutdown) events by default, and this app's lifespan
is where ``app.state.db``/``app.state.redis`` are created. ``TestClient``
handles that correctly and still exercises the (async) app underneath it.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from georisk.api.app import create_app
from georisk.settings import Settings


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        environment="development",
        database_url="postgresql+asyncpg://georisk:test@localhost:5432/georisk_test",
        redis_url="redis://localhost:6379/0",
    )


@pytest.fixture
def app(test_settings: Settings) -> FastAPI:
    return create_app(settings=test_settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c
