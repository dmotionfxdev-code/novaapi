"""End-to-end HTTP tests for the Workflow API and Workflow Query API against
a real Postgres instance — Identity (tenant + login) composed with
Assessment + WorkflowTemplate + WorkflowEngine, exactly as a real client
would use all three together.
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
        database_url=database_url, jwt_secret_key="test-secret-key-for-workflow-api-tests"
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        yield client


def _register_and_login(client: TestClient, suffix: str, role_name: str = "OWNER") -> dict:
    registration = client.post(
        "/api/v1/tenants",
        json={
            "name": f"Workflow API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@workflowapi.example",
            "owner_email": f"owner-{suffix}@workflowapi.example",
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
            json={"email": f"second-{suffix}@workflowapi.example", "role_name": role_name},
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
                "email": f"second-{suffix}@workflowapi.example",
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
            "name": f"HTTP Test Template {suffix}",
            "stage_definitions": [
                {"stage_type": "HAZARD", "trigger_mode": "AUTOMATIC"},
                {"stage_type": "EXPOSURE", "trigger_mode": "AUTOMATIC"},
                {"stage_type": "VULNERABILITY", "trigger_mode": "AUTOMATIC"},
                {
                    "stage_type": "RISK",
                    "required_predecessors": ["HAZARD", "EXPOSURE", "VULNERABILITY"],
                    "trigger_mode": "AUTOMATIC",
                },
            ],
        },
    )
    assert create.status_code == 201, create.text
    assert create.json()["status"] == "DRAFT"
    template_id = create.json()["id"]

    publish = client.post(
        f"/api/v1/workflow-templates/{template_id}/actions/publish", headers=headers
    )
    assert publish.status_code == 200, publish.text
    assert publish.json()["status"] == "PUBLISHED"
    return template_id


def test_full_workflow_lifecycle_via_http(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
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
    assert start.json()["status"] == "VALIDATED"  # all-AUTOMATIC template runs to completion

    workflow = api_client.get(f"/api/v1/assessments/{assessment_id}/workflow", headers=headers)
    assert workflow.status_code == 200, workflow.text
    body = workflow.json()
    assert body["workflow_template_id"] == template_id
    assert body["assessment_status"] == "VALIDATED"
    statuses = {e["stage_type"]: e["status"] for e in body["entries"]}
    assert statuses == {
        "HAZARD": "COMPLETE",
        "EXPOSURE": "COMPLETE",
        "VULNERABILITY": "COMPLETE",
        "RISK": "COMPLETE",
    }


def test_manual_stage_execute_route_via_http(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)

    create_template = api_client.post(
        "/api/v1/workflow-templates",
        headers=headers,
        json={
            "hazard_type": "FLOOD",
            "name": f"Manual Template {suffix}",
            "stage_definitions": [
                {"stage_type": "HAZARD", "trigger_mode": "MANUAL"},
            ],
        },
    )
    assert create_template.status_code == 201, create_template.text
    template_id = create_template.json()["id"]
    api_client.post(f"/api/v1/workflow-templates/{template_id}/actions/publish", headers=headers)

    create = api_client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Manual Flow", "hazard_type": "FLOOD"},
    )
    assessment_id = create.json()["id"]
    api_client.post(f"/api/v1/assessments/{assessment_id}/actions/mark-ready", headers=headers)

    start = api_client.post(
        f"/api/v1/assessments/{assessment_id}/actions/start-workflow",
        headers=headers,
        json={"workflow_template_id": template_id},
    )
    assert start.status_code == 200
    assert start.json()["status"] == "RUNNING"  # blocked — MANUAL stage never auto-dispatched

    execute = api_client.post(
        f"/api/v1/assessments/{assessment_id}/stages/HAZARD/actions/execute", headers=headers
    )
    assert execute.status_code == 200, execute.text
    assert execute.json()["assessment_status"] == "VALIDATED"


def test_viewer_cannot_create_workflow_template(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    viewer_headers = _register_and_login(api_client, suffix, role_name="VIEWER")

    response = api_client.post(
        "/api/v1/workflow-templates",
        headers=viewer_headers,
        json={
            "hazard_type": "FLOOD",
            "name": "Should Fail",
            "stage_definitions": [{"stage_type": "HAZARD"}],
        },
    )
    assert response.status_code == 403, response.text


def test_viewer_can_list_workflow_templates(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    owner_headers = _register_and_login(api_client, suffix)
    _create_and_publish_template(api_client, owner_headers, suffix)

    viewer_headers = _register_and_login(api_client, f"{suffix}-v", role_name="VIEWER")
    listing = api_client.get("/api/v1/workflow-templates", headers=viewer_headers)
    assert listing.status_code == 200
    assert isinstance(listing.json(), list)


def test_starting_workflow_with_mismatched_hazard_type_is_rejected(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    template_id = _create_and_publish_template(api_client, headers, suffix)  # hazard_type=FLOOD

    create = api_client.post(
        "/api/v1/assessments", headers=headers, json={"name": "Mismatch", "hazard_type": "DROUGHT"}
    )
    assessment_id = create.json()["id"]
    api_client.post(f"/api/v1/assessments/{assessment_id}/actions/mark-ready", headers=headers)

    start = api_client.post(
        f"/api/v1/assessments/{assessment_id}/actions/start-workflow",
        headers=headers,
        json={"workflow_template_id": template_id},
    )
    assert start.status_code == 422  # GuardRejectedError
