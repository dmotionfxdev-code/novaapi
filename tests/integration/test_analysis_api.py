"""End-to-end HTTP tests for the StageResult read API against a real
Postgres instance — Identity + Assessment + WorkflowTemplate + Workflow
Engine + Analysis (FIRAS strategy, wired exactly as production ``api/app
.py`` does) composed together, proving the whole cross-context wiring
works over real HTTP.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from georisk.api.app import create_app
from georisk.settings import Settings
from tests.integration._sprint_a_seed_helpers import seed_firas_indicator_datasets_sync

pytestmark = pytest.mark.integration


@pytest.fixture
def api_client():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = Settings(
        database_url=database_url, jwt_secret_key="test-secret-key-for-analysis-api-tests"
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        yield client


def _register_and_login(client: TestClient, suffix: str) -> dict:
    headers, _tenant_id = _register_and_login_with_tenant(client, suffix)
    return headers


def _register_and_login_with_tenant(client: TestClient, suffix: str) -> tuple[dict, str]:
    registration = client.post(
        "/api/v1/tenants",
        json={
            "name": f"Analysis API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@analysisapi.example",
            "owner_email": f"owner-{suffix}@analysisapi.example",
            "owner_password": "correct-horse-battery-staple",
        },
    )
    assert registration.status_code == 201, registration.text
    tenant_id = registration.json()["tenant"]["id"]
    owner_email = registration.json()["owner"]["email"]

    login = client.post(
        "/api/v1/auth/token",
        json={"email": owner_email, "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return headers, tenant_id


def _create_and_publish_firas_template(client: TestClient, headers: dict, suffix: str) -> str:
    create = client.post(
        "/api/v1/workflow-templates",
        headers=headers,
        json={
            "hazard_type": "FLOOD",
            "name": f"FIRAS API Template {suffix}",
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
                    "stage_type": "RESILIENCE",
                    "required_predecessors": ["VULNERABILITY"],
                    "trigger_mode": "AUTOMATIC",
                },
                {
                    "stage_type": "VALIDATION",
                    "required_predecessors": ["RISK", "RESILIENCE"],
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


def test_full_firas_workflow_via_http_and_stage_results_are_readable(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers, tenant_id = _register_and_login_with_tenant(api_client, suffix)
    template_id = _create_and_publish_firas_template(api_client, headers, suffix)

    # Sprint A: AnalysisStageExecutor now reads real Data Acquisition
    # datasets (CompositionRootIndicatorInputProvider), not
    # StubIndicatorInputProvider — seed the exact values the stub used to
    # fabricate, as a real cataloged dataset, so this test's downstream
    # assertions (exact FIRAS indicator values) still hold.
    seed_firas_indicator_datasets_sync(os.environ["DATABASE_URL"], tenant_id)

    create = api_client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Kigoma FIRAS", "hazard_type": "FLOOD"},
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

    listing = api_client.get(f"/api/v1/assessments/{assessment_id}/stage-results", headers=headers)
    assert listing.status_code == 200, listing.text
    stage_types = {r["stage_type"] for r in listing.json()["data"]}
    assert stage_types == {"HAZARD", "EXPOSURE", "VULNERABILITY", "RISK", "RESILIENCE"}

    hazard_detail = api_client.get(
        f"/api/v1/assessments/{assessment_id}/stage-results/HAZARD", headers=headers
    )
    assert hazard_detail.status_code == 200, hazard_detail.text
    body = hazard_detail.json()
    assert body["status"] == "COMPLETE"
    assert body["hazard_type"] == "FLOOD"
    indicators = {i["code"]: i["value"] for i in body["indicators"]}
    assert indicators["flood_hazard_index"] == pytest.approx(0.565)

    risk_detail = api_client.get(
        f"/api/v1/assessments/{assessment_id}/stage-results/RISK", headers=headers
    )
    assert risk_detail.status_code == 200
    risk_indicators = {i["code"]: i["value"] for i in risk_detail.json()["indicators"]}
    assert risk_indicators["flood_risk_index"] == pytest.approx(0.1101, abs=1e-4)
    assert risk_detail.json()["strategy_version"] == "firas-2.0"
    assert risk_detail.json()["formula_version"] == "fri-multiplicative-v2"


def test_unknown_stage_type_is_not_found(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    create = api_client.post(
        "/api/v1/assessments", headers=headers, json={"name": "X", "hazard_type": "FLOOD"}
    )
    assessment_id = create.json()["id"]

    response = api_client.get(
        f"/api/v1/assessments/{assessment_id}/stage-results/NOT_A_STAGE", headers=headers
    )
    assert response.status_code == 404


def test_cross_tenant_stage_results_are_not_visible(api_client: TestClient) -> None:
    suffix_a = uuid.uuid4().hex[:8]
    suffix_b = uuid.uuid4().hex[:8]
    headers_a = _register_and_login(api_client, suffix_a)
    headers_b = _register_and_login(api_client, suffix_b)
    template_id = _create_and_publish_firas_template(api_client, headers_a, suffix_a)

    create = api_client.post(
        "/api/v1/assessments", headers=headers_a, json={"name": "Tenant A", "hazard_type": "FLOOD"}
    )
    assessment_id = create.json()["id"]
    api_client.post(f"/api/v1/assessments/{assessment_id}/actions/mark-ready", headers=headers_a)
    api_client.post(
        f"/api/v1/assessments/{assessment_id}/actions/start-workflow",
        headers=headers_a,
        json={"workflow_template_id": template_id},
    )

    # Tenant B can't even see the assessment, so the stage-results route
    # 404s at the assessment-view permission boundary already exercised
    # elsewhere — here we confirm it doesn't leak stage-result data either.
    response = api_client.get(
        f"/api/v1/assessments/{assessment_id}/stage-results", headers=headers_b
    )
    assert response.status_code == 200
    assert response.json()["data"] == []
