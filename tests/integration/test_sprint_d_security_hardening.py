"""Sprint D — Security & Production Hardening. End-to-end HTTP tests
against a real Postgres instance, exactly like every other
``test_*_api.py`` file: proves genuine access-token revocation (logout,
password reset, suspend, explicit "revoke all sessions"), application-layer
rate limiting (with a tiny per-test override so the test stays fast and
deterministic), and that a Redis outage degrades gracefully rather than
breaking login/registration.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from georisk.api.app import create_app
from georisk.settings import Settings

pytestmark = pytest.mark.integration


def _settings(**overrides: object) -> Settings:
    database_url = os.environ["DATABASE_URL"]
    return Settings(
        database_url=database_url,
        jwt_secret_key="test-secret-key-for-sprint-d-tests",
        **overrides,
    )


@pytest.fixture
def api_client():
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    app = create_app(settings=_settings())
    with TestClient(app) as client:
        yield client


def _register_and_login(client: TestClient, suffix: str) -> tuple[dict, str, str]:
    registration = client.post(
        "/api/v1/tenants",
        json={
            "name": f"Sprint D Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@sprintd.example",
            "owner_email": f"owner-{suffix}@sprintd.example",
            "owner_password": "correct-horse-battery-staple",
        },
    )
    assert registration.status_code == 201, registration.text
    owner_email = registration.json()["owner"]["email"]

    login = client.post(
        "/api/v1/auth/token",
        json={"email": owner_email, "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200, login.text
    body = login.json()
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    return headers, body["access_token"], body["refresh_token"]


# --- 1. Access token revocation ---------------------------------------------


def test_logout_revokes_the_access_token_used_to_call_it(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers, _access_token, refresh_token = _register_and_login(api_client, suffix)

    # The token works before logout.
    me = api_client.get("/api/v1/users/me", headers=headers)
    assert me.status_code == 200

    logout = api_client.post(
        "/api/v1/auth/logout", headers=headers, json={"refresh_token": refresh_token}
    )
    assert logout.status_code == 204

    # The exact same access token must no longer authenticate.
    rejected = api_client.get("/api/v1/users/me", headers=headers)
    assert rejected.status_code == 401, rejected.text


def test_logout_without_authorization_header_still_works_idempotently(
    api_client: TestClient,
) -> None:
    """Pre-Sprint-D contract preserved: no ``Authorization`` header is
    required to log out, and repeating it is still a no-op 204."""
    suffix = uuid.uuid4().hex[:8]
    _headers, _access_token, refresh_token = _register_and_login(api_client, suffix)

    first = api_client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert first.status_code == 204
    second = api_client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert second.status_code == 204


def test_logout_does_not_revoke_a_different_sessions_access_token(api_client: TestClient) -> None:
    """Logout ends only the caller's own session — a second, independently
    logged-in session for the same account must remain valid."""
    suffix = uuid.uuid4().hex[:8]
    headers_1, _access_1, refresh_1 = _register_and_login(api_client, suffix)

    owner_email = f"owner-{suffix}@sprintd.example"
    second_login = api_client.post(
        "/api/v1/auth/token",
        json={"email": owner_email, "password": "correct-horse-battery-staple"},
    )
    assert second_login.status_code == 200
    headers_2 = {"Authorization": f"Bearer {second_login.json()['access_token']}"}

    logout_1 = api_client.post(
        "/api/v1/auth/logout", headers=headers_1, json={"refresh_token": refresh_1}
    )
    assert logout_1.status_code == 204

    # Session 1's access token is dead...
    assert api_client.get("/api/v1/users/me", headers=headers_1).status_code == 401
    # ...but session 2's is untouched.
    assert api_client.get("/api/v1/users/me", headers=headers_2).status_code == 200


def test_password_reset_revokes_every_previously_issued_access_token(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers, _access_token, _refresh_token = _register_and_login(api_client, suffix)
    owner_email = f"owner-{suffix}@sprintd.example"

    # Request + directly issue a known reset token (identical pattern to
    # test_identity_api.py's test_password_reset_flow — no notification
    # pipeline exists to deliver the real one over HTTP yet).
    import asyncio

    from georisk.contexts.identity.domain.tokens import PasswordResetToken
    from georisk.contexts.identity.infrastructure.repositories import (
        SqlAlchemyPasswordResetTokenRepository,
        SqlAlchemyUserRepository,
    )
    from georisk.contexts.identity.infrastructure.security import SecretsOpaqueTokenGenerator
    from georisk.db.session import Database

    token_gen = SecretsOpaqueTokenGenerator()
    raw_token = token_gen.generate()

    async def _issue_known_reset_token() -> None:
        db = Database(os.environ["DATABASE_URL"])
        async with db.session() as session:
            user = await SqlAlchemyUserRepository(session).get_by_email(owner_email)
            assert user is not None
            reset_token = PasswordResetToken.issue(
                user_id=user.id,
                tenant_id=user.tenant_id,
                token_hash=token_gen.hash_token(raw_token),
            )
            await SqlAlchemyPasswordResetTokenRepository(session).save(reset_token)
            await session.commit()
        await db.dispose()

    asyncio.run(_issue_known_reset_token())

    assert api_client.get("/api/v1/users/me", headers=headers).status_code == 200

    confirm = api_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"reset_token": raw_token, "new_password": "brand-new-password-77"},
    )
    assert confirm.status_code == 204

    rejected = api_client.get("/api/v1/users/me", headers=headers)
    assert rejected.status_code == 401, rejected.text


def test_suspending_a_user_revokes_their_previously_issued_access_token(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner_headers, _owner_access, _owner_refresh = _register_and_login(api_client, suffix)

    invite = api_client.post(
        "/api/v1/users",
        headers=owner_headers,
        json={"email": f"analyst-{suffix}@sprintd.example", "role_name": "ANALYST"},
    )
    assert invite.status_code == 201, invite.text
    analyst_id = invite.json()["user"]["id"]
    invitation_token = invite.json()["invitation_token"]

    accept = api_client.post(
        "/api/v1/users/invitations/accept",
        json={"invitation_token": invitation_token, "password": "another-strong-password-1"},
    )
    assert accept.status_code == 200, accept.text

    analyst_login = api_client.post(
        "/api/v1/auth/token",
        json={
            "email": f"analyst-{suffix}@sprintd.example",
            "password": "another-strong-password-1",
        },
    )
    assert analyst_login.status_code == 200
    analyst_headers = {"Authorization": f"Bearer {analyst_login.json()['access_token']}"}
    assert api_client.get("/api/v1/users/me", headers=analyst_headers).status_code == 200

    suspend = api_client.post(
        f"/api/v1/users/{analyst_id}/actions/suspend",
        headers=owner_headers,
        json={"reason": "test"},
    )
    assert suspend.status_code == 200, suspend.text

    # Even a permission-only route (not just get_current_user-based ones)
    # must reject the now-revoked token immediately — this is the exact
    # gap Sprint D's get_current_claims fix closes (require_permission
    # alone never used to re-check the database at all).
    rejected = api_client.get("/api/v1/users/me", headers=analyst_headers)
    assert rejected.status_code == 401, rejected.text


def test_revoke_all_sessions_endpoint_kills_every_active_session(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner_email = f"owner-{suffix}@sprintd.example"
    headers_1, _access_1, _refresh_1 = _register_and_login(api_client, suffix)

    second_login = api_client.post(
        "/api/v1/auth/token",
        json={"email": owner_email, "password": "correct-horse-battery-staple"},
    )
    assert second_login.status_code == 200
    headers_2 = {"Authorization": f"Bearer {second_login.json()['access_token']}"}

    revoke_all = api_client.post("/api/v1/auth/sessions/revoke-all", headers=headers_1)
    assert revoke_all.status_code == 204

    # Both sessions are dead — including the one that made the call itself.
    assert api_client.get("/api/v1/users/me", headers=headers_1).status_code == 401
    assert api_client.get("/api/v1/users/me", headers=headers_2).status_code == 401


def test_revoke_all_sessions_requires_authentication(api_client: TestClient) -> None:
    response = api_client.post("/api/v1/auth/sessions/revoke-all")
    assert response.status_code in (401, 403)


# --- 2. Application rate limiting -------------------------------------------


def test_login_is_rate_limited_per_ip() -> None:
    """A tiny per-test override (3/minute instead of the default 10) keeps
    this fast and deterministic regardless of the shared default."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = _settings(rate_limit_login_per_minute=3)
    app = create_app(settings=settings)
    with TestClient(app) as client:
        suffix = uuid.uuid4().hex[:8]
        registration = client.post(
            "/api/v1/tenants",
            json={
                "name": f"Rate Limit Test Co {suffix}",
                "tenant_email": f"contact-{suffix}@ratelimit.example",
                "owner_email": f"owner-{suffix}@ratelimit.example",
                "owner_password": "correct-horse-battery-staple",
            },
        )
        assert registration.status_code == 201

        # Deliberately wrong password — we only care about hitting the
        # rate-limit dependency, not about a successful login.
        statuses = [
            client.post(
                "/api/v1/auth/token",
                json={"email": f"owner-{suffix}@ratelimit.example", "password": "wrong"},
            ).status_code
            for _ in range(4)
        ]
        assert statuses[:3] == [401, 401, 401]
        assert statuses[3] == 429


def test_rate_limited_response_includes_retry_after_header() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = _settings(rate_limit_registration_per_hour=1)
    app = create_app(settings=settings)
    with TestClient(app) as client:
        suffix = uuid.uuid4().hex[:8]
        payload = {
            "name": f"Retry After Co {suffix}",
            "tenant_email": f"contact-{suffix}@retryafter.example",
            "owner_email": f"owner-{suffix}@retryafter.example",
            "owner_password": "correct-horse-battery-staple",
        }
        first = client.post("/api/v1/tenants", json=payload)
        assert first.status_code == 201

        second_payload = dict(payload, tenant_email=f"contact2-{suffix}@retryafter.example")
        second = client.post("/api/v1/tenants", json=second_payload)
        assert second.status_code == 429
        assert "Retry-After" in second.headers
        assert int(second.headers["Retry-After"]) > 0


def test_rate_limits_are_scoped_independently_per_bucket() -> None:
    """Hitting the (low) registration limit must not affect the (separate)
    login bucket for an already-registered account."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = _settings(rate_limit_registration_per_hour=1)
    app = create_app(settings=settings)
    with TestClient(app) as client:
        suffix = uuid.uuid4().hex[:8]
        payload = {
            "name": f"Bucket Scope Co {suffix}",
            "tenant_email": f"contact-{suffix}@bucketscope.example",
            "owner_email": f"owner-{suffix}@bucketscope.example",
            "owner_password": "correct-horse-battery-staple",
        }
        registration = client.post("/api/v1/tenants", json=payload)
        assert registration.status_code == 201

        # Registration bucket is now exhausted (limit=1)...
        blocked = client.post(
            "/api/v1/tenants", json=dict(payload, tenant_email=f"x-{suffix}@bucketscope.example")
        )
        assert blocked.status_code == 429

        # ...but login (a different bucket) still works fine.
        login = client.post(
            "/api/v1/auth/token",
            json={
                "email": f"owner-{suffix}@bucketscope.example",
                "password": "correct-horse-battery-staple",
            },
        )
        assert login.status_code == 200


# --- 3/4. Exception hardening + Redis graceful degradation ------------------


def test_health_ready_reports_degraded_not_unhealthy_when_only_redis_is_down() -> None:
    """Task #4: a Redis-only outage must not read the same as a database
    outage — the instance is still fully able to serve traffic (rate
    limiting silently falls back to its in-process counter)."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = _settings(redis_url="redis://127.0.0.1:1/0", redis_ratelimit_url="redis://127.0.0.1:1/0")
    app = create_app(settings=settings)
    with TestClient(app) as client:
        response = client.get("/health/ready")
        body = response.json()
        assert body["checks"]["redis"].startswith("error")
        assert body["checks"]["database"] == "ok"
        assert response.status_code == 200
        assert body["status"] == "degraded"


def test_login_still_works_when_redis_is_completely_unreachable() -> None:
    """The actual "application continues operating wherever safe" proof —
    not just the health check reporting it, but a real login (which now
    passes through the rate limiter on every call) succeeding anyway."""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = _settings(redis_url="redis://127.0.0.1:1/0", redis_ratelimit_url="redis://127.0.0.1:1/0")
    app = create_app(settings=settings)
    with TestClient(app) as client:
        suffix = uuid.uuid4().hex[:8]
        registration = client.post(
            "/api/v1/tenants",
            json={
                "name": f"Redis Down Co {suffix}",
                "tenant_email": f"contact-{suffix}@redisdown.example",
                "owner_email": f"owner-{suffix}@redisdown.example",
                "owner_password": "correct-horse-battery-staple",
            },
        )
        assert registration.status_code == 201, registration.text

        login = client.post(
            "/api/v1/auth/token",
            json={
                "email": f"owner-{suffix}@redisdown.example",
                "password": "correct-horse-battery-staple",
            },
        )
        assert login.status_code == 200, login.text
