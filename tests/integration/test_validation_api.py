"""End-to-end HTTP tests for the Validation API (API Resource Model §18)
against a real Postgres instance — Identity + Assessment + WorkflowTemplate
+ Workflow Engine + Validation composed together exactly as a real client
would use them, proving the whole cross-context wiring (composition root
included) works over real HTTP, not just in isolated unit tests.
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
        database_url=database_url, jwt_secret_key="test-secret-key-for-validation-api-tests"
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        yield client


def _register_and_login(client: TestClient, suffix: str, role_name: str = "OWNER") -> dict:
    registration = client.post(
        "/api/v1/tenants",
        json={
            "name": f"Validation API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@validationapi.example",
            "owner_email": f"owner-{suffix}@validationapi.example",
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
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    if role_name != "OWNER":
        invite = client.post(
            "/api/v1/users",
            headers=headers,
            json={"email": f"second-{suffix}@validationapi.example", "role_name": role_name},
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
                "email": f"second-{suffix}@validationapi.example",
                "password": "another-strong-password-1",
            },
        )
        assert second_login.status_code == 200
        headers = {"Authorization": f"Bearer {second_login.json()['access_token']}"}

    return headers


def _create_and_publish_template(client: TestClient, headers: dict, suffix: str) -> str:
    create = client.post(
        "/api/v1/workflow-templates",
        headers=headers,
        json={
            "hazard_type": "FLOOD",
            "name": f"Validation API Template {suffix}",
            "stage_definitions": [
                {"stage_type": "HAZARD", "trigger_mode": "AUTOMATIC"},
                {"stage_type": "EXPOSURE", "trigger_mode": "AUTOMATIC"},
                {"stage_type": "VULNERABILITY", "trigger_mode": "AUTOMATIC"},
                {
                    "stage_type": "RISK",
                    "required_predecessors": ["HAZARD", "EXPOSURE", "VULNERABILITY"],
                    "trigger_mode": "AUTOMATIC",
                },
                {
                    "stage_type": "VALIDATION",
                    "required_predecessors": ["RISK"],
                    "trigger_mode": "AUTOMATIC",
                },
            ],
        },
    )
    assert create.status_code == 201, create.text
    template_id = create.json()["id"]
    publish = client.post(
        f"/api/v1/workflow-templates/{template_id}/actions/publish", headers=headers
    )
    assert publish.status_code == 200, publish.text
    return template_id


def _create_running_assessment_with_validation(
    api_client: TestClient, headers: dict, suffix: str
) -> str:
    template_id = _create_and_publish_template(api_client, headers, suffix)
    create = api_client.post(
        "/api/v1/assessments", headers=headers, json={"name": "Kigoma Q3", "hazard_type": "FLOOD"}
    )
    assert create.status_code == 201, create.text
    assessment_id = create.json()["id"]
    ready = api_client.post(
        f"/api/v1/assessments/{assessment_id}/actions/mark-ready", headers=headers
    )
    assert ready.status_code == 200, ready.text
    start = api_client.post(
        f"/api/v1/assessments/{assessment_id}/actions/start-workflow",
        headers=headers,
        json={"workflow_template_id": template_id},
    )
    assert start.status_code == 200, start.text
    assert start.json()["status"] == "VALIDATED"
    return assessment_id


def test_validation_run_is_created_by_the_workflow_engine_and_listable(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    assessment_id = _create_running_assessment_with_validation(api_client, headers, suffix)

    listing = api_client.get(f"/api/v1/assessments/{assessment_id}/validations", headers=headers)
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert len(body["data"]) == 1
    run = body["data"][0]
    assert run["assessment_id"] == assessment_id
    assert run["issued_by"] == "system:workflow-engine"
    assert run["status"] == "COMPLETED"
    assert run["verdict"] in ("PASS", "FAIL")
    assert run["metrics"]["overall_accuracy"] is not None


def test_get_validation_run_detail_returns_full_metric_set(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    assessment_id = _create_running_assessment_with_validation(api_client, headers, suffix)

    listing = api_client.get(f"/api/v1/assessments/{assessment_id}/validations", headers=headers)
    run_id = listing.json()["data"][0]["id"]

    detail = api_client.get(
        f"/api/v1/assessments/{assessment_id}/validations/{run_id}", headers=headers
    )
    assert detail.status_code == 200, detail.text
    metrics = detail.json()["metrics"]
    assert "confusion_matrix" in metrics
    assert metrics["confusion_matrix"]["labels"] == ["NEGATIVE", "POSITIVE"]
    assert metrics["auc"] is not None
    assert metrics["roc_points"]


def test_ad_hoc_run_validation_via_http(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)

    create = api_client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Ad Hoc Target", "hazard_type": "FLOOD"},
    )
    assessment_id = create.json()["id"]

    run = api_client.post(
        f"/api/v1/assessments/{assessment_id}/validations/actions/run",
        headers=headers,
        json={"subject_id": "manual-subject-1", "subject_type": "STAGE_RESULT"},
    )
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["issued_by"] != "system:workflow-engine"
    assert body["subject_id"] == "manual-subject-1"


def test_viewer_cannot_run_ad_hoc_validation(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    viewer_headers = _register_and_login(api_client, suffix, role_name="VIEWER")

    create_as_viewer = viewer_headers  # viewer also can't create assessments, so use owner's
    owner_headers = _register_and_login(api_client, f"{suffix}-o")
    create = api_client.post(
        "/api/v1/assessments", headers=owner_headers, json={"name": "X", "hazard_type": "FLOOD"}
    )
    assessment_id = create.json()["id"]

    response = api_client.post(
        f"/api/v1/assessments/{assessment_id}/validations/actions/run",
        headers=create_as_viewer,
        json={"subject_id": "x", "subject_type": "STAGE_RESULT"},
    )
    assert response.status_code == 403, response.text


def test_validation_run_not_found_across_assessments(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    assessment_id = _create_running_assessment_with_validation(api_client, headers, suffix)

    listing = api_client.get(f"/api/v1/assessments/{assessment_id}/validations", headers=headers)
    run_id = listing.json()["data"][0]["id"]

    other_assessment = api_client.post(
        "/api/v1/assessments", headers=headers, json={"name": "Other", "hazard_type": "DROUGHT"}
    )
    other_assessment_id = other_assessment.json()["id"]

    response = api_client.get(
        f"/api/v1/assessments/{other_assessment_id}/validations/{run_id}", headers=headers
    )
    assert response.status_code == 404
