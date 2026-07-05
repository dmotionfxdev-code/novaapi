"""Sprint 0 Review finding #14 / Remediation #14 — validation method: two
``create_app()`` instances configured with different database URLs must own
genuinely independent engines, not share a process-global one. This is what
makes the app-factory pattern's own stated test-isolation rationale
(Implementation Bootstrap §3) actually true rather than aspirational.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from georisk.api.app import create_app
from georisk.settings import Settings

pytestmark = pytest.mark.integration


def test_two_app_instances_own_independent_engines() -> None:
    settings_a = Settings(
        database_url="postgresql+asyncpg://georisk:test@localhost:5432/georisk_test_a",
        redis_url="redis://localhost:6379/0",
    )
    settings_b = Settings(
        database_url="postgresql+asyncpg://georisk:test@localhost:5432/georisk_test_b",
        redis_url="redis://localhost:6379/0",
    )

    app_a = create_app(settings=settings_a)
    app_b = create_app(settings=settings_b)

    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        # Each app's lifespan has run by now, populating app.state.db.
        db_a = client_a.app.state.db
        db_b = client_b.app.state.db

        assert db_a is not db_b
        assert db_a.engine is not db_b.engine
        assert str(db_a.engine.url) != str(db_b.engine.url)
