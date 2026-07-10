"""Sprint D exception hardening — unit tests against a minimal standalone
FastAPI app (not the full ``create_app()``, no database needed): proves an
unhandled exception's real message/type never reaches the client, while a
recognized domain error's own deliberately-safe message still passes
through unchanged (regression protection for the pre-Sprint-D behavior
every other integration test already relies on, e.g.
``test_wrong_password_returns_401_not_403``).
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from georisk.api.middleware.error_handling import register_exception_handlers
from georisk.shared_kernel.errors import RateLimitExceededError, ValidationFailedError

pytestmark = pytest.mark.unit


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom-internal")
    async def boom_internal() -> None:
        raise RuntimeError("password=hunter2 connection to 10.0.0.5:5432 failed")

    @app.get("/boom-validation")
    async def boom_validation() -> None:
        raise ValidationFailedError("email is not a valid email address")

    @app.get("/boom-rate-limit")
    async def boom_rate_limit() -> None:
        raise RateLimitExceededError(
            "Too many requests — try again in 42 seconds", retry_after_seconds=42
        )

    return app


def test_unhandled_exception_never_leaks_its_real_message() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    response = client.get("/boom-internal")
    assert response.status_code == 500
    body = response.json()
    assert "hunter2" not in response.text
    assert "10.0.0.5" not in response.text
    assert "RuntimeError" not in response.text
    assert body["detail"] == (
        "An unexpected error occurred. Please contact support with this trace ID."
    )
    assert body["title"] == "InternalServerError"
    assert "traceId" in body and body["traceId"]


def test_unhandled_exception_response_still_has_a_traceid_even_without_trace_middleware() -> None:
    """This app has no ``TraceContextMiddleware`` (that's ``api/app.py``'s
    job) — the handler must still produce *some* traceId rather than
    omitting the field, per ``_trace_id``'s own fallback chain."""
    client = TestClient(_app(), raise_server_exceptions=False)
    response = client.get("/boom-internal")
    assert len(response.json()["traceId"]) > 0


def test_recognized_domain_error_still_surfaces_its_own_safe_message() -> None:
    """Regression guard: Sprint D's hardening must only change the
    catch-all 500 path — every already-mapped domain error (400-429) keeps
    returning its own deliberately-crafted message unchanged."""
    client = TestClient(_app(), raise_server_exceptions=False)
    response = client.get("/boom-validation")
    assert response.status_code == 400
    assert response.json()["detail"] == "email is not a valid email address"


def test_rate_limit_exceeded_maps_to_429_with_retry_after_header() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    response = client.get("/boom-rate-limit")
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "42"
    assert "42 seconds" in response.json()["detail"]
