"""End-to-end HTTP tests against a real Postgres instance — Identity
(tenant registration + login) composed with Assessment (full lifecycle),
exactly as a real client would use both together. The clearest possible
proof that the corrected import-linter contract (Sprint 2: identity as a
one-directional shared kernel) produces a genuinely working integration,
not just a passing lint check.
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
    settings = Settings(
        database_url=database_url, jwt_secret_key="test-secret-key-for-assessment-api-tests"
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        yield client


def _register_and_login(client: TestClient, suffix: str, role_name: str = "OWNER") -> dict:
    registration = client.post(
        "/api/v1/tenants",
        json={
            "name": f"Assessment API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@assessapi.example",
            "owner_email": f"owner-{suffix}@assessapi.example",
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
    tokens = login.json()
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    if role_name != "OWNER":
        # Invite + accept a second user with the desired role, to test
        # permission boundaries below Owner.
        invite = client.post(
            "/api/v1/users",
            headers=headers,
            json={"email": f"second-{suffix}@assessapi.example", "role_name": role_name},
        )
        assert invite.status_code == 201, invite.text
        accept = client.post(
            "/api/v1/users/invitations/accept",
            json={
                "invitation_token": invite.json()["invitation_token"],
                "password": "another-strong-password-1",
            },
        )
        assert accept.status_code == 200, accept.text
        second_login = client.post(
            "/api/v1/auth/token",
            json={
                "email": f"second-{suffix}@assessapi.example",
                "password": "another-strong-password-1",
            },
        )
        assert second_login.status_code == 200
        headers = {"Authorization": f"Bearer {second_login.json()['access_token']}"}

    return headers


def test_full_assessment_lifecycle_via_http(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)

    # 1. Create.
    create = api_client.post(
        "/api/v1/assessments", headers=headers, json={"name": "Kigoma Q3", "hazard_type": "FLOOD"}
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["status"] == "DRAFT"
    assert body["hazard_type"] == "FLOOD"
    assessment_id = body["id"]

    # 2. Get.
    get_resp = api_client.get(f"/api/v1/assessments/{assessment_id}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "Kigoma Q3"

    # 3. mark-ready -> start -> validate -> report -> archive.
    ready = api_client.post(
        f"/api/v1/assessments/{assessment_id}/actions/mark-ready", headers=headers
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "READY"

    start = api_client.post(f"/api/v1/assessments/{assessment_id}/actions/start", headers=headers)
    assert start.status_code == 200
    assert start.json()["status"] == "RUNNING"

    validate = api_client.post(
        f"/api/v1/assessments/{assessment_id}/actions/validate", headers=headers
    )
    assert validate.status_code == 200
    assert validate.json()["status"] == "VALIDATED"

    report = api_client.post(f"/api/v1/assessments/{assessment_id}/actions/report", headers=headers)
    assert report.status_code == 200
    assert report.json()["status"] == "REPORTED"

    archive = api_client.post(
        f"/api/v1/assessments/{assessment_id}/actions/archive", headers=headers
    )
    assert archive.status_code == 200
    assert archive.json()["status"] == "ARCHIVED"

    # 4. Illegal transition from a terminal state -> 409.
    illegal = api_client.post(f"/api/v1/assessments/{assessment_id}/actions/start", headers=headers)
    assert illegal.status_code == 409, illegal.text

    # 5. List with a status filter finds it.
    listing = api_client.get("/api/v1/assessments", headers=headers, params={"status": "ARCHIVED"})
    assert listing.status_code == 200
    ids = {a["id"] for a in listing.json()["data"]}
    assert assessment_id in ids


def test_cancel_flow_via_http(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)

    create = api_client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "To Be Cancelled", "hazard_type": "DROUGHT"},
    )
    assessment_id = create.json()["id"]

    cancel = api_client.post(
        f"/api/v1/assessments/{assessment_id}/actions/cancel",
        headers=headers,
        json={"reason": "duplicate assessment"},
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "CANCELLED"
    assert cancel.json()["cancellation_reason"] == "duplicate assessment"

    # Cancelling again is illegal (already terminal).
    cancel_again = api_client.post(
        f"/api/v1/assessments/{assessment_id}/actions/cancel",
        headers=headers,
        json={"reason": "again"},
    )
    assert cancel_again.status_code == 409


def test_cancel_requires_a_reason(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    create = api_client.post(
        "/api/v1/assessments", headers=headers, json={"name": "No Reason", "hazard_type": "FLOOD"}
    )
    assessment_id = create.json()["id"]

    response = api_client.post(
        f"/api/v1/assessments/{assessment_id}/actions/cancel", headers=headers, json={"reason": ""}
    )
    assert response.status_code == 422  # Pydantic min_length=1 validation


def test_viewer_role_cannot_create_assessment(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    viewer_headers = _register_and_login(api_client, suffix, role_name="VIEWER")

    response = api_client.post(
        "/api/v1/assessments",
        headers=viewer_headers,
        json={"name": "Should Fail", "hazard_type": "FLOOD"},
    )
    assert response.status_code == 403, response.text


def test_viewer_role_can_view_assessments(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner_headers = _register_and_login(api_client, suffix)
    create = api_client.post(
        "/api/v1/assessments",
        headers=owner_headers,
        json={"name": "Viewable", "hazard_type": "FLOOD"},
    )
    assert create.status_code == 201

    # Re-derive a viewer session against the SAME tenant by inviting one.
    invite = api_client.post(
        "/api/v1/users",
        headers=owner_headers,
        json={"email": f"viewer-{suffix}@assessapi.example", "role_name": "VIEWER"},
    )
    assert invite.status_code == 201
    accept = api_client.post(
        "/api/v1/users/invitations/accept",
        json={
            "invitation_token": invite.json()["invitation_token"],
            "password": "viewer-password-123",
        },
    )
    assert accept.status_code == 200
    viewer_login = api_client.post(
        "/api/v1/auth/token",
        json={"email": f"viewer-{suffix}@assessapi.example", "password": "viewer-password-123"},
    )
    viewer_headers = {"Authorization": f"Bearer {viewer_login.json()['access_token']}"}

    listing = api_client.get("/api/v1/assessments", headers=viewer_headers)
    assert listing.status_code == 200
    assert len(listing.json()["data"]) >= 1


def test_cross_tenant_assessment_is_not_found(api_client: TestClient) -> None:
    suffix_a = uuid.uuid4().hex[:8]
    suffix_b = uuid.uuid4().hex[:8]
    headers_a = _register_and_login(api_client, suffix_a)
    headers_b = _register_and_login(api_client, suffix_b)

    create = api_client.post(
        "/api/v1/assessments",
        headers=headers_a,
        json={"name": "Tenant A's", "hazard_type": "FLOOD"},
    )
    assessment_id = create.json()["id"]

    response = api_client.get(f"/api/v1/assessments/{assessment_id}", headers=headers_b)
    assert response.status_code == 404


def test_unauthenticated_request_is_rejected(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/assessments")
    assert response.status_code in (401, 403)
