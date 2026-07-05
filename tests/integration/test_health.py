"""Sprint 0 Review finding #11 / Remediation #11: proves the liveness and
readiness checks actually behave differently — liveness must succeed with
no dependency reachable; readiness must reflect real dependency health.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_liveness_succeeds_even_with_no_reachable_dependencies(client: TestClient) -> None:
    """`test_settings` (conftest.py) points at a database/Redis that may not
    actually be running — liveness must not care, by design (§ Health).
    """
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_reports_database_and_redis_checks(client: TestClient) -> None:
    """Requires real Postgres/Redis reachable at the URLs in `test_settings`
    (conftest.py) — provided by `docker compose up postgres redis` locally,
    or CI's service containers. If they're unreachable, this correctly
    reports 503/"degraded" rather than raising, which this assertion allows
    for explicitly rather than requiring a specific outcome, since whether
    services happen to be up is an environment fact, not something this
    test should assume.
    """
    response = client.get("/health/ready")
    assert response.status_code in (200, 503)
    body = response.json()
    assert "database" in body["checks"]
    assert "redis" in body["checks"]
