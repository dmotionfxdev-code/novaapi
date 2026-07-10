"""End-to-end HTTP tests for the Regression Validation extension against a
real Postgres instance — Identity + Assessment + Geospatial + Data
Acquisition + Prediction + Validation + Reporting composed together,
exercising the REAL composition-root resolver
(``CompositionRootRegressionValidationSubjectResolver``) against a
genuinely-produced ``PredictionRun``, proving Sprint 10's "Integrate with
Prediction Context"/"Integrate with Reporting Context" requirements work
end-to-end over real HTTP.
"""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from georisk.api.app import create_app
from georisk.settings import Settings
from tests.integration._sprint_a_seed_helpers import seed_real_wildfire_hazard_observations_sync

pytestmark = pytest.mark.integration

_SQUARE_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]],
}

# Sprint A: CompositionRootPredictionDataProvider reads real completed
# Analysis outputs instead of StubPredictionDataProvider's on-demand
# synthetic fabrication — see test_prediction_api.py for why these exact
# values (non-collinear predictors, wind_speed in [0, 1] since it's also
# WRRAS's own raw HAZARD indicator key).
_NDVI_VALUES = [0.10, 0.22, 0.15, 0.30, 0.18, 0.35, 0.12, 0.28, 0.20, 0.33]
_WIND_SPEED_VALUES = [0.30, 0.55, 0.80, 0.42, 0.95, 0.28, 0.71, 0.60, 0.90, 0.48]
_BURNED_AREA_VALUES = [0.05, 0.12, 0.09, 0.18, 0.10, 0.20, 0.06, 0.16, 0.11, 0.19]


@pytest.fixture
def api_client():  # noqa: ANN201
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = Settings(
        database_url=database_url,
        jwt_secret_key="test-secret-key-for-validation-regression-api-tests",
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        yield client


def _register_and_login(client: TestClient, suffix: str) -> dict:
    registration = client.post(
        "/api/v1/tenants",
        json={
            "name": f"Regression Validation API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@regvalapi.example",
            "owner_email": f"owner-{suffix}@regvalapi.example",
            "owner_password": "correct-horse-battery-staple",
        },
    )
    assert registration.status_code == 201, registration.text
    owner_email = registration.json()["owner"]["email"]
    tenant_id = registration.json()["tenant"]["id"]
    # Sprint A: real completed Analysis outputs, sharing the exact
    # variable codes _build_prediction_run registers below, so
    # CompositionRootPredictionDataProvider has real rows to read.
    observations = [
        {"ndvi": ndvi, "wind_speed": wind, "burned_area": burned}
        for ndvi, wind, burned in zip(
            _NDVI_VALUES, _WIND_SPEED_VALUES, _BURNED_AREA_VALUES, strict=True
        )
    ]
    seed_real_wildfire_hazard_observations_sync(
        os.environ["DATABASE_URL"], tenant_id, observations
    )

    login = client.post(
        "/api/v1/auth/token",
        json={"email": owner_email, "password": "correct-horse-battery-staple"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _build_prediction_run(client: TestClient, headers: dict, method: str) -> dict:
    """Registers predictor variables (2 independent + 1 dependent),
    confirms a VariableSelection, defines an AOI, generates a
    SamplingCampaign, and runs a prediction — Sprint 8's full prerequisite
    chain — returning ``{"assessment_id":..., "prediction_run_id":...}``.
    """
    create = client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Regression Validation Test", "hazard_type": "WILDFIRE"},
    )
    assert create.status_code == 201, create.text
    assessment_id = create.json()["id"]

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
            "name": "Regression validation vars",
            "hazard_type": "WILDFIRE",
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
        json={"source": "DRAWN", "geometry": _SQUARE_GEOJSON, "name": "Regression Val AOI"},
    )
    assert aoi.status_code == 201, aoi.text
    aoi_id = aoi.json()["id"]

    campaign = client.post(
        f"/api/v1/assessments/{assessment_id}/sampling-campaigns",
        headers=headers,
        json={
            "aoi_id": aoi_id,
            "name": "Regression Val Campaign",
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
            "method": method,
        },
    )
    assert run.status_code == 201, run.text
    assert run.json()["status"] == "COMPLETED"
    return {"assessment_id": assessment_id, "prediction_run_id": run.json()["id"]}


def test_run_regression_validation_against_a_real_mlr_prediction_via_http(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    ctx = _build_prediction_run(api_client, headers, "MULTIPLE_LINEAR_REGRESSION")

    validate = api_client.post(
        f"/api/v1/assessments/{ctx['assessment_id']}/validations/actions/run-regression",
        headers=headers,
        json={"subject_id": ctx["prediction_run_id"]},
    )
    assert validate.status_code == 201, validate.text
    body = validate.json()
    assert body["mode"] == "REGRESSION"
    assert body["subject_type"] == "PREDICTION"
    assert body["subject_id"] == ctx["prediction_run_id"]
    assert body["status"] == "COMPLETED"
    assert body["verdict"] in ("PASS", "FAIL")
    assert body["metrics"] is None
    assert body["regression_metrics"] is not None
    assert body["regression_metrics"]["rmse"] >= 0.0
    assert body["regression_metrics"]["r_squared"] <= 1.0
    assert body["model_metadata"] is not None
    assert body["model_metadata"]["method"] == "MULTIPLE_LINEAR_REGRESSION"
    assert body["model_metadata"]["formula_version"] == "mlr-ols-v1"
    assert set(body["model_metadata"]["predictor_variable_codes"]) == {"ndvi", "wind_speed"}
    assert body["model_metadata"]["dependent_variable_code"] == "burned_area"

    # Listing/detail reads work identically to the classification path.
    listing = api_client.get(
        f"/api/v1/assessments/{ctx['assessment_id']}/validations", headers=headers
    )
    assert listing.status_code == 200
    assert len(listing.json()["data"]) == 1

    detail = api_client.get(
        f"/api/v1/assessments/{ctx['assessment_id']}/validations/{body['id']}", headers=headers
    )
    assert detail.status_code == 200
    assert detail.json()["mode"] == "REGRESSION"


def test_run_regression_validation_against_a_correlation_run_fails_gracefully_via_http(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    ctx = _build_prediction_run(api_client, headers, "PEARSON_CORRELATION")

    validate = api_client.post(
        f"/api/v1/assessments/{ctx['assessment_id']}/validations/actions/run-regression",
        headers=headers,
        json={"subject_id": ctx["prediction_run_id"]},
    )
    assert validate.status_code == 201, validate.text
    body = validate.json()
    assert body["status"] == "FAILED"
    assert body["regression_metrics"] is None
    assert "no regression fit" in body["error"]


def test_regression_validation_summary_appears_in_generated_report_via_http(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    ctx = _build_prediction_run(api_client, headers, "MULTIPLE_LINEAR_REGRESSION")

    validate = api_client.post(
        f"/api/v1/assessments/{ctx['assessment_id']}/validations/actions/run-regression",
        headers=headers,
        json={"subject_id": ctx["prediction_run_id"]},
    )
    assert validate.status_code == 201, validate.text

    report = api_client.post(
        f"/api/v1/assessments/{ctx['assessment_id']}/reports/actions/generate", headers=headers
    )
    assert report.status_code == 201, report.text
    validation_summary = report.json()["validation_summary"]
    assert validation_summary is not None
    assert validation_summary["mode"] == "REGRESSION"
    assert validation_summary["rmse"] is not None
    assert validation_summary["r_squared"] is not None
    assert validation_summary["overall_accuracy"] is None
