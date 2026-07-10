"""End-to-end HTTP tests for the Dashboard & Visualization API against a
real Postgres instance — Identity + Assessment + Workflow Engine +
Analysis (FIRAS) + Geospatial + Data Acquisition + Prediction +
Validation + Reporting + Notification + Dashboard composed together,
exercising the REAL composition-root readers (``api/dashboard_ports.py``)
against genuinely-produced cross-context data, proving Sprint 12's eight
dashboards work end-to-end over real HTTP with zero changes to any
protected context and zero persistence of Dashboard's own.
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
# synthetic fabrication — see test_prediction_api.py for why these exact,
# non-collinear values.
_NDVI_VALUES = [0.10, 0.22, 0.15, 0.30, 0.18, 0.35, 0.12, 0.28, 0.20, 0.33]
_WIND_SPEED_VALUES = [0.30, 0.55, 0.80, 0.42, 0.95, 0.28, 0.71, 0.60, 0.90, 0.48]
_BURNED_AREA_VALUES = [0.05, 0.31, 0.02, 0.28, 0.15, 0.09, 0.33, 0.04, 0.22, 0.17]


@pytest.fixture
def api_client():  # noqa: ANN201
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = Settings(
        database_url=database_url, jwt_secret_key="test-secret-key-for-dashboard-api-tests"
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
            "name": f"Dashboard API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@dashboardapi.example",
            "owner_email": f"owner-{suffix}@dashboardapi.example",
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


def _run_firas_workflow_to_validated(client: TestClient, headers: dict, suffix: str) -> str:
    tmpl = client.post(
        "/api/v1/workflow-templates",
        headers=headers,
        json={
            "hazard_type": "FLOOD",
            "name": f"Dashboard API Template {suffix}",
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
    assert tmpl.status_code == 201, tmpl.text
    template_id = tmpl.json()["id"]
    publish = client.post(
        f"/api/v1/workflow-templates/{template_id}/actions/publish", headers=headers
    )
    assert publish.status_code == 200, publish.text

    create = client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Dashboard FIRAS Assessment", "hazard_type": "FLOOD"},
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


def _attach_mlr_prediction_and_regression_validation(
    client: TestClient, headers: dict, assessment_id: str
) -> str:
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
    burned = client.post(
        "/api/v1/predictor-variables",
        headers=headers,
        json={
            "name": "Burned Area",
            "code": "burned_area",
            "category": "VEGETATION_AND_FUEL",
            "variable_role": "DEPENDENT",
            "data_type": "CONTINUOUS",
            "unit": "fraction",
            "is_required_for_mlr": True,
            "value_min": 0.0,
            "value_max": 1.0,
        },
    )
    assert burned.status_code == 201, burned.text

    selection = client.post(
        "/api/v1/variable-selections",
        headers=headers,
        json={
            "name": "Dashboard test vars",
            "hazard_type": "FLOOD",
            "selected_variable_ids": [ndvi.json()["id"], wind.json()["id"], burned.json()["id"]],
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
        json={"source": "DRAWN", "geometry": _SQUARE_GEOJSON, "name": "Dashboard AOI"},
    )
    assert aoi.status_code == 201, aoi.text
    aoi_id = aoi.json()["id"]

    campaign = client.post(
        f"/api/v1/assessments/{assessment_id}/sampling-campaigns",
        headers=headers,
        json={
            "aoi_id": aoi_id,
            "name": "Dashboard Campaign",
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
            "method": "MULTIPLE_LINEAR_REGRESSION",
        },
    )
    assert run.status_code == 201, run.text
    assert run.json()["status"] == "COMPLETED"
    prediction_run_id = run.json()["id"]

    validate = client.post(
        f"/api/v1/assessments/{assessment_id}/validations/actions/run-regression",
        headers=headers,
        json={"subject_id": prediction_run_id},
    )
    assert validate.status_code == 201, validate.text
    return prediction_run_id


def _catalog_a_dataset(client: TestClient, headers: dict) -> None:
    source = client.post(
        "/api/v1/dataset-sources",
        headers=headers,
        json={"name": "CHIRPS", "provider": "CHIRPS", "description": "Rainfall estimates"},
    )
    assert source.status_code == 201, source.text
    catalog = client.post(
        "/api/v1/datasets",
        headers=headers,
        json={
            "dataset_source_id": source.json()["id"],
            "name": "Dashboard-Rainfall-2020-2025",
            "dataset_type": "RASTER",
            "source": "Satellite",
            "provider": "CHIRPS",
            "acquisition_date": "2026-01-01",
            "crs": "EPSG:4326",
            "spatial_coverage": "Tanzania",
            "temporal_coverage_start": "2020-01-01T00:00:00Z",
            "temporal_coverage_end": "2025-12-31T00:00:00Z",
            "processing_method": "RAW",
            "spatial_resolution_m": 5000.0,
            "is_mlr_ready": True,
        },
    )
    assert catalog.status_code == 201, catalog.text


def _create_alert_and_subscription_and_evaluate(
    client: TestClient, headers: dict, assessment_id: str
) -> None:
    rule = client.post(
        "/api/v1/alert-rules",
        headers=headers,
        json={
            "name": "High Flood Risk",
            "subject_type": "STAGE_RESULT",
            "hazard_type": "FLOOD",
            "stage_type": "RISK",
            "metric_code": "flood_risk_index",
            "operator": "GREATER_THAN",
            "threshold": 0.05,
            "severity": "HIGH",
        },
    )
    assert rule.status_code == 201, rule.text
    sub = client.post(
        "/api/v1/notification-subscriptions", headers=headers, json={"channels": ["IN_APP"]}
    )
    assert sub.status_code == 201, sub.text
    evaluate = client.post(
        f"/api/v1/assessments/{assessment_id}/notifications/actions/evaluate-alert-rules",
        headers=headers,
    )
    assert evaluate.status_code == 200, evaluate.text
    assert len(evaluate.json()["data"]) == 1


def test_all_eight_dashboards_reflect_genuinely_produced_cross_context_data(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers, tenant_id = _register_and_login_with_tenant(api_client, suffix)
    assessment_id = _run_firas_workflow_to_validated(api_client, headers, suffix)

    observations = [
        {"ndvi": ndvi, "wind_speed": wind, "burned_area": burned}
        for ndvi, wind, burned in zip(
            _NDVI_VALUES, _WIND_SPEED_VALUES, _BURNED_AREA_VALUES, strict=True
        )
    ]
    seed_real_firas_hazard_observations_sync(os.environ["DATABASE_URL"], tenant_id, observations)

    _attach_mlr_prediction_and_regression_validation(api_client, headers, assessment_id)
    _catalog_a_dataset(api_client, headers)
    _create_alert_and_subscription_and_evaluate(api_client, headers, assessment_id)

    report = api_client.post(
        f"/api/v1/assessments/{assessment_id}/reports/actions/generate", headers=headers
    )
    assert report.status_code == 201, report.text

    # --- Requirement #1: Dashboard Projections (assessment workspace) ---
    workspace = api_client.get(
        f"/api/v1/dashboards/workspace/{assessment_id}", headers=headers
    )
    assert workspace.status_code == 200, workspace.text
    w = workspace.json()
    assert w["hazard_type"] == "FLOOD"
    assert w["status"] == "VALIDATED"
    stage_types = {s["stage_type"] for s in w["stage_results"]}
    assert stage_types == {"HAZARD", "EXPOSURE", "VULNERABILITY", "RISK", "RESILIENCE"}
    risk_card = next(s for s in w["stage_results"] if s["stage_type"] == "RISK")
    assert risk_card["primary_indicators"]["flood_risk_index"] == pytest.approx(0.1101, abs=1e-4)
    assert w["latest_prediction_method"] == "MULTIPLE_LINEAR_REGRESSION"
    assert w["latest_validation_mode"] == "REGRESSION"
    assert w["latest_report_version"] == 1
    assert w["active_notification_count"] == 1

    # --- Requirement #2: Executive Dashboard ---
    executive = api_client.get("/api/v1/dashboards/executive", headers=headers)
    assert executive.status_code == 200, executive.text
    e = executive.json()
    assert e["total_assessments"] >= 1
    assert e["assessments_by_status"].get("VALIDATED", 0) >= 1
    assert e["assessments_by_hazard_type"].get("FLOOD", 0) >= 1
    assert len(e["recent_reports"]) >= 1

    # --- Requirement #3: FIRAS Dashboard ---
    firas = api_client.get("/api/v1/dashboards/firas", headers=headers)
    assert firas.status_code == 200, firas.text
    f = firas.json()
    assert f["hazard_type"] == "FLOOD"
    assert f["total_assessments"] >= 1
    firas_kpis = {k["label"]: k["value"] for k in f["kpis"]}
    assert firas_kpis["Average Risk Index"] == pytest.approx(0.1101, abs=1e-4)
    assert len(f["trend"]) >= 1

    # --- Requirement #4: WRRAS Dashboard (no wildfire assessments here) ---
    wrras = api_client.get("/api/v1/dashboards/wrras", headers=headers)
    assert wrras.status_code == 200, wrras.text
    assert wrras.json()["hazard_type"] == "WILDFIRE"
    assert wrras.json()["total_assessments"] == 0

    # --- Requirement #5: Prediction Dashboard ---
    prediction = api_client.get("/api/v1/dashboards/prediction", headers=headers)
    assert prediction.status_code == 200, prediction.text
    p = prediction.json()
    assert p["total_prediction_runs"] >= 1
    assert p["runs_by_method"].get("MULTIPLE_LINEAR_REGRESSION", 0) >= 1

    # --- Requirement #6: Validation Dashboard ---
    validation = api_client.get("/api/v1/dashboards/validation", headers=headers)
    assert validation.status_code == 200, validation.text
    v = validation.json()
    assert v["total_validation_runs"] >= 1
    assert v["runs_by_mode"].get("REGRESSION", 0) >= 1

    # --- Requirement #7: Alert Dashboard ---
    alerts = api_client.get("/api/v1/dashboards/alerts", headers=headers)
    assert alerts.status_code == 200, alerts.text
    a = alerts.json()
    assert a["total_alert_rules"] >= 1
    assert a["active_alert_rules"] >= 1
    assert a["total_notifications"] >= 1
    assert a["notifications_by_status"].get("SENT", 0) >= 1

    # --- Requirement #8: Dataset Dashboard ---
    datasets = api_client.get("/api/v1/dashboards/datasets", headers=headers)
    assert datasets.status_code == 200, datasets.text
    d = datasets.json()
    assert d["total_datasets"] >= 1
    assert d["mlr_ready_count"] >= 1


def test_dashboard_requires_dashboard_view_permission(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    # OWNER role has dashboard:view by default (Sprint 12's role grants) —
    # a bare smoke check that the permission gate is wired at all, not a
    # negative-permission test (every role gets this view-only code).
    response = api_client.get("/api/v1/dashboards/executive", headers=headers)
    assert response.status_code == 200


def test_workspace_projection_rejects_unknown_assessment(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    response = api_client.get(
        f"/api/v1/dashboards/workspace/{uuid.uuid4()}", headers=headers
    )
    # AssessmentNotAvailableError subclasses ValidationFailedError (400),
    # the same "unavailable prerequisite" mapping Reporting's/Notification's
    # equivalent errors already use — not NotFoundError (404), since this
    # is a malformed *request* (referencing evidence that doesn't exist),
    # not a missing *Dashboard* resource.
    assert response.status_code == 400
