"""End-to-end HTTP tests for the StageResult read API against a real
Postgres instance, for WRRAS — mirrors ``test_analysis_api.py``'s FIRAS
coverage, proving the identical cross-context wiring (Identity +
Assessment + WorkflowTemplate + Workflow Engine + Analysis) works over
real HTTP for a second hazard type, wired exactly as production
``api/app.py`` does (both strategies registered together).
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from georisk.api.app import create_app
from georisk.settings import Settings
from tests.integration._sprint_a_seed_helpers import seed_wrras_indicator_datasets_sync

pytestmark = pytest.mark.integration


@pytest.fixture
def api_client():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = Settings(
        database_url=database_url, jwt_secret_key="test-secret-key-for-wrras-api-tests"
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        yield client


def _register_and_login(client: TestClient, suffix: str) -> dict:
    registration = client.post(
        "/api/v1/tenants",
        json={
            "name": f"WRRAS API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@wrrasapi.example",
            "owner_email": f"owner-{suffix}@wrrasapi.example",
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
    # Sprint A: AnalysisStageExecutor now reads real Data Acquisition
    # datasets (CompositionRootIndicatorInputProvider), not
    # StubIndicatorInputProvider — seed the exact values the stub used to
    # fabricate, as a real cataloged dataset, so every test in this file
    # that drives a WRRAS workflow to completion still sees the same
    # numbers it always asserted on.
    tenant_id = registration.json()["tenant"]["id"]
    seed_wrras_indicator_datasets_sync(os.environ["DATABASE_URL"], tenant_id)
    return headers


def _create_and_publish_wrras_template(client: TestClient, headers: dict, suffix: str) -> str:
    create = client.post(
        "/api/v1/workflow-templates",
        headers=headers,
        json={
            "hazard_type": "WILDFIRE",
            "name": f"WRRAS API Template {suffix}",
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


def test_full_wrras_workflow_via_http_and_stage_results_are_readable(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    template_id = _create_and_publish_wrras_template(api_client, headers, suffix)

    create = api_client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Serengeti WRRAS", "hazard_type": "WILDFIRE"},
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
    assert body["hazard_type"] == "WILDFIRE"
    indicators = {i["code"]: i["value"] for i in body["indicators"]}
    assert indicators["wildfire_hazard_index"] == pytest.approx(0.58)

    risk_detail = api_client.get(
        f"/api/v1/assessments/{assessment_id}/stage-results/RISK", headers=headers
    )
    assert risk_detail.status_code == 200
    risk_indicators = {i["code"]: i["value"] for i in risk_detail.json()["indicators"]}
    assert risk_indicators["wildfire_risk_index"] == pytest.approx(0.0926, abs=1e-4)
    assert risk_detail.json()["strategy_version"] == "wrras-1.0"
    assert risk_detail.json()["formula_version"] == "wri-multiplicative-v1"


def test_flood_and_wildfire_assessments_coexist_independently(api_client: TestClient) -> None:
    """The core extensibility claim, over real HTTP: registering WRRAS
    alongside FIRAS disturbs neither — one tenant can run both hazard
    types' assessments side by side."""
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    wrras_template_id = _create_and_publish_wrras_template(api_client, headers, suffix)

    flood_create = api_client.post(
        "/api/v1/assessments", headers=headers, json={"name": "Flood Co", "hazard_type": "FLOOD"}
    )
    assert flood_create.status_code == 201, flood_create.text

    wildfire_create = api_client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Wildfire Co", "hazard_type": "WILDFIRE"},
    )
    assert wildfire_create.status_code == 201, wildfire_create.text
    wildfire_id = wildfire_create.json()["id"]

    api_client.post(f"/api/v1/assessments/{wildfire_id}/actions/mark-ready", headers=headers)
    start = api_client.post(
        f"/api/v1/assessments/{wildfire_id}/actions/start-workflow",
        headers=headers,
        json={"workflow_template_id": wrras_template_id},
    )
    assert start.status_code == 200, start.text
    assert start.json()["status"] == "VALIDATED"
