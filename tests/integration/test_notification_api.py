"""End-to-end HTTP tests for the Notification & Early Warning API against
a real Postgres instance — Identity + Assessment + Workflow Engine +
Analysis (FIRAS) + Geospatial + Data Acquisition + Prediction +
Validation + Notification composed together, exercising the REAL
composition-root readers (``CompositionRootAssessmentReader``/
``CompositionRootAlertMetricReader``) against genuinely-produced
cross-context data, proving Sprint 11's Early Warning Engine works
end-to-end over real HTTP with zero changes to any protected context.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from georisk.api.app import create_app
from georisk.settings import Settings

pytestmark = pytest.mark.integration

_SQUARE_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]],
}


@pytest.fixture
def api_client():  # noqa: ANN201
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = Settings(
        database_url=database_url, jwt_secret_key="test-secret-key-for-notification-api-tests"
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        yield client


def _register_and_login(client: TestClient, suffix: str) -> dict:
    registration = client.post(
        "/api/v1/tenants",
        json={
            "name": f"Notification API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@notifyapi.example",
            "owner_email": f"owner-{suffix}@notifyapi.example",
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
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_and_publish_firas_template(client: TestClient, headers: dict, suffix: str) -> str:
    create = client.post(
        "/api/v1/workflow-templates",
        headers=headers,
        json={
            "hazard_type": "FLOOD",
            "name": f"Notification API Template {suffix}",
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


def _run_firas_workflow_to_validated(client: TestClient, headers: dict, suffix: str) -> str:
    template_id = _create_and_publish_firas_template(client, headers, suffix)
    create = client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Notification FIRAS Assessment", "hazard_type": "FLOOD"},
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
    """Sprint 8/10's full prerequisite chain, returning the resulting
    PredictionRun id so a Prediction-subject alert rule has real data."""
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
            "name": "Notification test vars",
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
        json={"source": "DRAWN", "geometry": _SQUARE_GEOJSON, "name": "Notification AOI"},
    )
    assert aoi.status_code == 201, aoi.text
    aoi_id = aoi.json()["id"]

    campaign = client.post(
        f"/api/v1/assessments/{assessment_id}/sampling-campaigns",
        headers=headers,
        json={
            "aoi_id": aoi_id,
            "name": "Notification Campaign",
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


def test_full_early_warning_flow_across_flood_prediction_and_validation_alerts(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    assessment_id = _run_firas_workflow_to_validated(api_client, headers, suffix)
    _attach_mlr_prediction_and_regression_validation(api_client, headers, assessment_id)

    flood_rule = api_client.post(
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
    assert flood_rule.status_code == 201, flood_rule.text
    assert flood_rule.json()["is_active"] is True

    prediction_rule = api_client.post(
        "/api/v1/alert-rules",
        headers=headers,
        json={
            "name": "High RMSE",
            "subject_type": "PREDICTION",
            "metric_code": "rmse",
            "operator": "GREATER_THAN",
            "threshold": 0.01,
            "severity": "MEDIUM",
        },
    )
    assert prediction_rule.status_code == 201, prediction_rule.text

    validation_rule = api_client.post(
        "/api/v1/alert-rules",
        headers=headers,
        json={
            "name": "Low R-squared",
            "subject_type": "VALIDATION",
            "metric_code": "r_squared",
            "operator": "LESS_THAN",
            "threshold": 0.99,
            "severity": "CRITICAL",
        },
    )
    assert validation_rule.status_code == 201, validation_rule.text

    # A rule scoped to WILDFIRE must never fire for this FLOOD assessment.
    wildfire_rule = api_client.post(
        "/api/v1/alert-rules",
        headers=headers,
        json={
            "name": "High Wildfire Risk",
            "subject_type": "STAGE_RESULT",
            "hazard_type": "WILDFIRE",
            "stage_type": "RISK",
            "metric_code": "wildfire_risk_index",
            "operator": "GREATER_THAN",
            "threshold": 0.01,
            "severity": "HIGH",
        },
    )
    assert wildfire_rule.status_code == 201, wildfire_rule.text

    subscription = api_client.post(
        "/api/v1/notification-subscriptions",
        headers=headers,
        json={"channels": ["IN_APP"]},
    )
    assert subscription.status_code == 201, subscription.text
    assert subscription.json()["is_active"] is True

    evaluate = api_client.post(
        f"/api/v1/assessments/{assessment_id}/notifications/actions/evaluate-alert-rules",
        headers=headers,
    )
    assert evaluate.status_code == 200, evaluate.text
    notifications = evaluate.json()["data"]
    assert len(notifications) == 3
    metric_codes = {n["metric_code"] for n in notifications}
    assert metric_codes == {"flood_risk_index", "rmse", "r_squared"}
    for n in notifications:
        assert n["status"] == "SENT"
        assert n["channel"] == "IN_APP"

    flood_notification = next(n for n in notifications if n["metric_code"] == "flood_risk_index")
    assert flood_notification["severity"] == "HIGH"
    assert flood_notification["triggered_value"] == pytest.approx(0.1101, abs=1e-4)

    validation_notification = next(n for n in notifications if n["metric_code"] == "r_squared")
    assert validation_notification["severity"] == "CRITICAL"

    listing = api_client.get(
        f"/api/v1/assessments/{assessment_id}/notifications", headers=headers
    )
    assert listing.status_code == 200
    assert len(listing.json()["data"]) == 3

    history = api_client.get("/api/v1/notifications", headers=headers)
    assert history.status_code == 200
    assert len(history.json()["data"]) == 3


def test_alert_rule_crud_and_deactivation_stops_it_from_firing(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    assessment_id = _run_firas_workflow_to_validated(api_client, headers, suffix)

    create = api_client.post(
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
    assert create.status_code == 201, create.text
    rule_id = create.json()["id"]

    updated = api_client.post(
        f"/api/v1/alert-rules/{rule_id}/actions/update-threshold",
        headers=headers,
        json={"threshold": 0.99},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["threshold"] == 0.99

    api_client.post(
        "/api/v1/notification-subscriptions", headers=headers, json={"channels": ["IN_APP"]}
    )

    # threshold now 0.99, flood_risk_index is ~0.11 — should not fire.
    evaluate = api_client.post(
        f"/api/v1/assessments/{assessment_id}/notifications/actions/evaluate-alert-rules",
        headers=headers,
    )
    assert evaluate.status_code == 200
    assert evaluate.json()["data"] == []

    deactivated = api_client.post(
        f"/api/v1/alert-rules/{rule_id}/actions/deactivate", headers=headers
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    listing = api_client.get("/api/v1/alert-rules", headers=headers)
    assert listing.status_code == 200
    assert len(listing.json()["data"]) == 1
