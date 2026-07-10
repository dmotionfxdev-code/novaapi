"""End-to-end HTTP tests for the Reporting API against a real Postgres
instance — Identity + Assessment + Workflow Engine + Analysis (FIRAS) +
Geospatial + Data Acquisition + Prediction + Validation + Reporting
composed together, exercising the REAL composition-root readers
(``CompositionRootAssessmentReader``/``CompositionRootStageResultReader``/
``CompositionRootPredictionReader``/``CompositionRootDatasetCatalogReader``/
``CompositionRootValidationReader``) against genuinely-produced
cross-context data, proving Sprint 9's Reporting context works end-to-end
over real HTTP with zero platform changes.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from georisk.api.app import create_app
from georisk.settings import Settings
from tests.integration._sprint_a_seed_helpers import (
    seed_firas_indicator_datasets_sync,
    seed_real_firas_hazard_observations_sync,
)

pytestmark = pytest.mark.integration

_SQUARE_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]],
}

# Sprint A: CompositionRootPredictionDataProvider reads real completed
# Analysis outputs instead of StubPredictionDataProvider's on-demand
# synthetic fabrication — non-collinear so Pearson correlation gets a
# genuine, non-degenerate pair to compute.
_NDVI_VALUES = [0.10, 0.22, 0.15, 0.30, 0.18, 0.35, 0.12, 0.28, 0.20, 0.33]
_WIND_SPEED_VALUES = [0.30, 0.55, 0.80, 0.42, 0.95, 0.28, 0.71, 0.60, 0.90, 0.48]


@pytest.fixture
def api_client():  # noqa: ANN201
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = Settings(
        database_url=database_url, jwt_secret_key="test-secret-key-for-reporting-api-tests"
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
            "name": f"Reporting API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@reportingapi.example",
            "owner_email": f"owner-{suffix}@reportingapi.example",
            "owner_password": "correct-horse-battery-staple",
        },
    )
    assert registration.status_code == 201, registration.text
    tenant_id = registration.json()["tenant"]["id"]
    owner_email = registration.json()["owner"]["email"]
    # Sprint A: AnalysisStageExecutor now reads real Data Acquisition
    # datasets (CompositionRootIndicatorInputProvider), not
    # StubIndicatorInputProvider — seed the exact values the stub used to
    # fabricate, as a real cataloged dataset, so a FIRAS workflow started
    # for this tenant still runs to completion with the same exact
    # indicator values this file's assertions depend on.
    seed_firas_indicator_datasets_sync(os.environ["DATABASE_URL"], tenant_id)

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
            "name": f"Reporting API Template {suffix}",
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


def _run_firas_workflow_to_validated(
    client: TestClient, headers: dict, suffix: str
) -> str:
    template_id = _create_and_publish_firas_template(client, headers, suffix)
    create = client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Reporting FIRAS Assessment", "hazard_type": "FLOOD"},
    )
    assert create.status_code == 201, create.text
    assessment_id = create.json()["id"]

    ready = client.post(f"/api/v1/assessments/{assessment_id}/actions/mark-ready", headers=headers)
    assert ready.status_code == 200, ready.text

    start = client.post(
        f"/api/v1/assessments/{assessment_id}/actions/start-workflow",
        headers=headers,
        json={"workflow_template_id": template_id},
    )
    assert start.status_code == 200, start.text
    assert start.json()["status"] == "VALIDATED"
    return assessment_id


def _attach_prediction_run(client: TestClient, headers: dict, assessment_id: str) -> None:
    """Registers predictor variables, confirms a VariableSelection, defines
    an AOI, generates a SamplingCampaign, and runs a Pearson correlation —
    the full Sprint 8 prerequisite chain — so this assessment has a real
    ``PredictionRun`` for Reporting's predictor summary section."""
    ndvi = client.post(
        "/api/v1/predictor-variables",
        headers=headers,
        json={
            "name": "NDVI",
            "code": "ndvi",
            "category": "VEGETATION_AND_FUEL",
            "variable_role": "INDEPENDENT",
            "data_type": "CONTINUOUS",
            "unit": "index",
            "is_required_for_mlr": True,
            "value_min": -1.0,
            "value_max": 1.0,
        },
    )
    assert ndvi.status_code == 201, ndvi.text
    wind = client.post(
        "/api/v1/predictor-variables",
        headers=headers,
        json={
            "name": "Wind Speed",
            "code": "wind_speed",
            "category": "METEOROLOGICAL",
            "variable_role": "INDEPENDENT",
            "data_type": "CONTINUOUS",
            "unit": "m/s",
            "is_required_for_mlr": True,
            "value_min": 0.0,
            "value_max": 30.0,
        },
    )
    assert wind.status_code == 201, wind.text

    selection = client.post(
        "/api/v1/variable-selections",
        headers=headers,
        json={
            "name": "Reporting test variables",
            "hazard_type": "FLOOD",
            "selected_variable_ids": [ndvi.json()["id"], wind.json()["id"]],
        },
    )
    assert selection.status_code == 201, selection.text
    selection_id = selection.json()["id"]
    confirm = client.post(
        f"/api/v1/variable-selections/{selection_id}/actions/confirm", headers=headers
    )
    assert confirm.status_code == 200, confirm.text

    aoi = client.post(
        f"/api/v1/assessments/{assessment_id}/aoi",
        headers=headers,
        json={"source": "DRAWN", "geometry": _SQUARE_GEOJSON, "name": "Reporting AOI"},
    )
    assert aoi.status_code == 201, aoi.text
    aoi_id = aoi.json()["id"]

    campaign = client.post(
        f"/api/v1/assessments/{assessment_id}/sampling-campaigns",
        headers=headers,
        json={
            "aoi_id": aoi_id,
            "name": "Reporting Campaign",
            "method": "SIMPLE_RANDOM",
            "sample_size": 1000,
        },
    )
    assert campaign.status_code == 201, campaign.text
    campaign_id = campaign.json()["id"]
    generate = client.post(
        f"/api/v1/assessments/{assessment_id}/sampling-campaigns/{campaign_id}"
        "/actions/generate-points",
        headers=headers,
    )
    assert generate.status_code == 200, generate.text

    run = client.post(
        f"/api/v1/assessments/{assessment_id}/predictions/actions/run",
        headers=headers,
        json={
            "variable_selection_id": selection_id,
            "sampling_campaign_id": campaign_id,
            "method": "PEARSON_CORRELATION",
        },
    )
    assert run.status_code == 201, run.text
    assert run.json()["status"] == "COMPLETED"


def test_generate_and_finalize_report_via_http(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers, tenant_id = _register_and_login_with_tenant(api_client, suffix)
    assessment_id = _run_firas_workflow_to_validated(api_client, headers, suffix)

    # Sprint A: real completed Analysis outputs sharing the exact
    # variable codes _attach_prediction_run registers below, so
    # CompositionRootPredictionDataProvider has real rows to correlate.
    observations = [
        {"ndvi": ndvi, "wind_speed": wind}
        for ndvi, wind in zip(_NDVI_VALUES, _WIND_SPEED_VALUES, strict=True)
    ]
    seed_real_firas_hazard_observations_sync(os.environ["DATABASE_URL"], tenant_id, observations)

    _attach_prediction_run(api_client, headers, assessment_id)

    generate = api_client.post(
        f"/api/v1/assessments/{assessment_id}/reports/actions/generate", headers=headers
    )
    assert generate.status_code == 201, generate.text
    body = generate.json()
    assert body["status"] == "DRAFT"
    assert body["version"] == 1

    assert body["assessment_summary"]["hazard_type"] == "FLOOD"
    assert body["assessment_summary"]["aoi_name"] == "Reporting AOI"
    assert body["assessment_summary"]["sample_count"] == 1000

    assert body["risk_summary"] is not None
    stage_types = {s["stage_type"] for s in body["risk_summary"]["stages"]}
    assert stage_types == {"HAZARD", "EXPOSURE", "VULNERABILITY", "RISK", "RESILIENCE"}
    risk_stage = next(s for s in body["risk_summary"]["stages"] if s["stage_type"] == "RISK")
    assert risk_stage["indicators"]["flood_risk_index"] == pytest.approx(0.1101, abs=1e-4)
    assert body["strategy_version"] == "firas-2.0"
    formula_versions = {f["stage_type"]: f["formula_version"] for f in body["formula_versions"]}
    assert formula_versions["RISK"] == "fri-multiplicative-v2"

    assert len(body["predictor_summary"]) == 1
    prediction_entry = body["predictor_summary"][0]
    assert prediction_entry["method"] == "PEARSON_CORRELATION"
    assert len(prediction_entry["correlation_pairs"]) == 1

    assert body["validation_summary"] is not None
    assert body["validation_summary"]["verdict"] in ("PASS", "FAIL")

    report_id = body["id"]

    finalize = api_client.post(
        f"/api/v1/assessments/{assessment_id}/reports/{report_id}/actions/finalize",
        headers=headers,
    )
    assert finalize.status_code == 200, finalize.text
    assert finalize.json()["status"] == "FINALIZED"
    assert finalize.json()["finalized_by"]

    # A DRAFT once finalized can't be finalized again.
    refinalize = api_client.post(
        f"/api/v1/assessments/{assessment_id}/reports/{report_id}/actions/finalize",
        headers=headers,
    )
    assert refinalize.status_code == 409, refinalize.text

    latest = api_client.get(
        f"/api/v1/assessments/{assessment_id}/reports/latest", headers=headers
    )
    assert latest.status_code == 200
    assert latest.json()["id"] == report_id
    assert latest.json()["status"] == "FINALIZED"

    listing = api_client.get(f"/api/v1/assessments/{assessment_id}/reports", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()["data"]) == 1

    dashboard = api_client.get("/api/v1/dashboard/reports", headers=headers)
    assert dashboard.status_code == 200
    dashboard_assessment_ids = {r["assessment_id"] for r in dashboard.json()["data"]}
    assert assessment_id in dashboard_assessment_ids


def test_re_generating_report_creates_new_version_via_http(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    assessment_id = _run_firas_workflow_to_validated(api_client, headers, suffix)

    first = api_client.post(
        f"/api/v1/assessments/{assessment_id}/reports/actions/generate", headers=headers
    )
    assert first.status_code == 201, first.text
    assert first.json()["version"] == 1

    second = api_client.post(
        f"/api/v1/assessments/{assessment_id}/reports/actions/generate", headers=headers
    )
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2


def test_generate_report_for_assessment_with_no_optional_data_via_http(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    create = api_client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Bare Assessment", "hazard_type": "FLOOD"},
    )
    assert create.status_code == 201, create.text
    assessment_id = create.json()["id"]

    generate = api_client.post(
        f"/api/v1/assessments/{assessment_id}/reports/actions/generate", headers=headers
    )
    assert generate.status_code == 201, generate.text
    body = generate.json()
    assert body["status"] == "DRAFT"
    assert body["risk_summary"] is None
    assert body["predictor_summary"] == []
    assert body["validation_summary"] is None
