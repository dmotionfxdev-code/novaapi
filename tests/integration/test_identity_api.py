"""End-to-end HTTP tests against a real Postgres instance — the highest-
value tests in this sprint: they exercise routing, dependency injection,
authentication, authorization, and the full command/handler stack together,
exactly as a real client would.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from georisk.api.app import create_app
from georisk.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
def api_client():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = Settings(database_url=database_url, jwt_secret_key="test-secret-key-for-api-tests")
    app = create_app(settings=settings)
    with TestClient(app) as client:
        yield client


def _register_tenant(client: TestClient, suffix: str) -> dict:
    response = client.post(
        "/api/v1/tenants",
        json={
            "name": f"API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@apitest.example",
            "owner_email": f"owner-{suffix}@apitest.example",
            "owner_password": "correct-horse-battery-staple",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_full_tenant_and_user_lifecycle(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]

    # 1. Register tenant + owner.
    registration = _register_tenant(api_client, suffix)
    owner_email = registration["owner"]["email"]
    assert registration["tenant"]["slug"].startswith("api-test-co")
    assert registration["owner"]["role_name"] == "OWNER"
    assert registration["owner"]["status"] == "ACTIVE"

    # 2. Login as owner.
    login = api_client.post(
        "/api/v1/auth/token",
        json={"email": owner_email, "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200, login.text
    tokens = login.json()
    assert tokens["token_type"] == "bearer"
    owner_headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    # 3. GET /users/me reflects the owner.
    me = api_client.get("/api/v1/users/me", headers=owner_headers)
    assert me.status_code == 200
    assert me.json()["email"] == owner_email

    # 4. Invite an analyst.
    invite = api_client.post(
        "/api/v1/users",
        headers=owner_headers,
        json={"email": f"analyst-{suffix}@apitest.example", "role_name": "ANALYST"},
    )
    assert invite.status_code == 201, invite.text
    invitation_token = invite.json()["invitation_token"]
    analyst_id = invite.json()["user"]["id"]
    assert invite.json()["user"]["status"] == "INVITED"

    # 5. Accept the invitation (public endpoint, no auth).
    accept = api_client.post(
        "/api/v1/users/invitations/accept",
        json={"invitation_token": invitation_token, "password": "another-strong-password-1"},
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["status"] == "ACTIVE"

    # 6. Analyst logs in.
    analyst_login = api_client.post(
        "/api/v1/auth/token",
        json={
            "email": f"analyst-{suffix}@apitest.example",
            "password": "another-strong-password-1",
        },
    )
    assert analyst_login.status_code == 200
    analyst_headers = {"Authorization": f"Bearer {analyst_login.json()['access_token']}"}

    # 7. Analyst can view their own profile...
    analyst_me = api_client.get("/api/v1/users/me", headers=analyst_headers)
    assert analyst_me.status_code == 200
    assert analyst_me.json()["role_name"] == "ANALYST"

    # 8. ...but cannot invite users (lacks user:invite permission) -> 403.
    forbidden = api_client.post(
        "/api/v1/users",
        headers=analyst_headers,
        json={"email": "nope@apitest.example", "role_name": "VIEWER"},
    )
    assert forbidden.status_code == 403, forbidden.text

    # 9. Owner lists users — sees both.
    listing = api_client.get("/api/v1/users", headers=owner_headers)
    assert listing.status_code == 200
    emails = {u["email"] for u in listing.json()["data"]}
    assert owner_email in emails
    assert f"analyst-{suffix}@apitest.example" in emails

    # 10. Owner promotes the analyst to ADMIN.
    promote = api_client.post(
        f"/api/v1/users/{analyst_id}/actions/change-role",
        headers=owner_headers,
        json={"role_name": "ADMIN"},
    )
    assert promote.status_code == 200, promote.text
    assert promote.json()["role_name"] == "ADMIN"

    # 11. Owner suspends the (now-admin) user.
    suspend = api_client.post(
        f"/api/v1/users/{analyst_id}/actions/suspend",
        headers=owner_headers,
        json={"reason": "test"},
    )
    assert suspend.status_code == 200
    assert suspend.json()["status"] == "SUSPENDED"

    # 12. Suspended user cannot log in -> 401 (authentication failure, not 403).
    suspended_login = api_client.post(
        "/api/v1/auth/token",
        json={
            "email": f"analyst-{suffix}@apitest.example",
            "password": "another-strong-password-1",
        },
    )
    assert suspended_login.status_code == 401, suspended_login.text

    # 13. Owner reactivates them.
    reactivate = api_client.post(
        f"/api/v1/users/{analyst_id}/actions/reactivate", headers=owner_headers
    )
    assert reactivate.status_code == 200
    assert reactivate.json()["status"] == "ACTIVE"

    # 14. Refresh token rotation via the API.
    refresh = api_client.post(
        "/api/v1/auth/token/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh.status_code == 200
    new_tokens = refresh.json()
    assert new_tokens["refresh_token"] != tokens["refresh_token"]

    # 15. The old refresh token is now dead (rotated away).
    reuse = api_client.post(
        "/api/v1/auth/token/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reuse.status_code == 401

    # 16. Logout is idempotent and returns 204 either way.
    logout1 = api_client.post(
        "/api/v1/auth/logout", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert logout1.status_code == 204
    logout2 = api_client.post(
        "/api/v1/auth/logout", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert logout2.status_code == 204

    # 17. Roles catalog is reachable and has all four seeded roles.
    roles = api_client.get("/api/v1/roles", headers=owner_headers)
    assert roles.status_code == 200
    assert {r["name"] for r in roles.json()} == {"OWNER", "ADMIN", "ANALYST", "VIEWER"}


def test_wrong_password_returns_401_not_403(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    registration = _register_tenant(api_client, suffix)
    response = api_client.post(
        "/api/v1/auth/token",
        json={"email": registration["owner"]["email"], "password": "totally-wrong-password"},
    )
    assert response.status_code == 401
    body = response.json()
    assert body["status"] == 401
    assert "traceId" in body


def test_unauthenticated_request_is_rejected(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/users/me")
    assert response.status_code in (401, 403)  # HTTPBearer's own missing-credentials response


def test_password_reset_flow(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    registration = _register_tenant(api_client, suffix)
    owner_email = registration["owner"]["email"]

    # Request never reveals whether the email exists.
    request_resp = api_client.post(
        "/api/v1/auth/password-reset/request", json={"email": owner_email}
    )
    assert request_resp.status_code == 202

    unknown_resp = api_client.post(
        "/api/v1/auth/password-reset/request", json={"email": "nobody-here@apitest.example"}
    )
    assert unknown_resp.status_code == 202
    assert unknown_resp.json() == request_resp.json()

    # The raw token is deliberately never in the HTTP response (see
    # handlers_auth.py's module docstring) — a real client only ever learns
    # it via the out-of-band delivery channel Notification will provide
    # (Roadmap Sprint 10). For this test, issue one directly through the
    # same domain/repository code the handler itself uses, with a
    # known raw value, exactly as if that out-of-band delivery had happened.
    import asyncio

    from georisk.contexts.identity.domain.tokens import PasswordResetToken
    from georisk.contexts.identity.infrastructure.repositories import (
        SqlAlchemyPasswordResetTokenRepository,
        SqlAlchemyUserRepository,
    )
    from georisk.contexts.identity.infrastructure.security import SecretsOpaqueTokenGenerator
    from georisk.db.session import Database

    database_url = os.environ["DATABASE_URL"]
    token_gen = SecretsOpaqueTokenGenerator()
    raw_token = token_gen.generate()

    async def _issue_known_reset_token() -> None:
        db = Database(database_url)
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

    confirm = api_client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"reset_token": raw_token, "new_password": "brand-new-password-99"},
    )
    assert confirm.status_code == 204, confirm.text

    # Old password no longer works; new one does.
    old_login = api_client.post(
        "/api/v1/auth/token",
        json={"email": owner_email, "password": "correct-horse-battery-staple"},
    )
    assert old_login.status_code == 401

    new_login = api_client.post(
        "/api/v1/auth/token", json={"email": owner_email, "password": "brand-new-password-99"}
    )
    assert new_login.status_code == 200
