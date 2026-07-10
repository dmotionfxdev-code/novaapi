"""End-to-end HTTP tests for the Prediction API against a real Postgres
instance — Identity + Assessment + Geospatial + Data Acquisition +
Prediction composed together, exercising the REAL composition-root
readers (``CompositionRootVariableSelectionReader``/
``CompositionRootSamplingCampaignReader``) over genuinely-created
cross-context data, proving Sprint 8's "no platform changes required"
wiring works end-to-end over real HTTP.
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

# Sprint A: CompositionRootPredictionDataProvider reads real completed
# Analysis outputs instead of StubPredictionDataProvider's on-demand
# synthetic fabrication — these hand-picked, non-collinear observation
# sets give correlation/MLR a real, well-conditioned design matrix to fit
# against (ndvi and wind_speed deliberately do NOT vary in lockstep, so
# the regression's X'X matrix isn't singular). ``wind_speed`` values are
# deliberately in [0, 1] (not literal m/s) — this same key name is ALSO
# WRRAS's own raw HAZARD indicator (a normalized index), whose calculator
# validates it strictly to that range; the Prediction PredictorVariable
# registered below with value_min/max 0/30 is metadata only, never
# enforced at runtime, so satisfying WRRAS's real constraint is what
# actually matters here.
_NDVI_VALUES = [0.10, 0.22, 0.15, 0.30, 0.18, 0.35, 0.12, 0.28, 0.20, 0.33]
_WIND_SPEED_VALUES = [0.30, 0.55, 0.80, 0.42, 0.95, 0.28, 0.71, 0.60, 0.90, 0.48]
_BURNED_AREA_VALUES = [0.05, 0.12, 0.09, 0.18, 0.10, 0.20, 0.06, 0.16, 0.11, 0.19]
_REAL_OBSERVATION_COUNT = len(_NDVI_VALUES)

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
        database_url=database_url, jwt_secret_key="test-secret-key-for-prediction-api-tests"
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
            "name": f"Prediction API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@predictionapi.example",
            "owner_email": f"owner-{suffix}@predictionapi.example",
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


def _seed_real_observations(tenant_id: str) -> None:
    observations = [
        {"ndvi": ndvi, "wind_speed": wind, "burned_area": burned}
        for ndvi, wind, burned in zip(
            _NDVI_VALUES, _WIND_SPEED_VALUES, _BURNED_AREA_VALUES, strict=True
        )
    ]
    seed_real_wildfire_hazard_observations_sync(
        os.environ["DATABASE_URL"], tenant_id, observations
    )


def _build_prediction_ready_assessment(client: TestClient, headers: dict) -> dict:
    """Registers predictor variables (2 independent + 1 dependent),
    confirms a VariableSelection, defines an AOI, and generates a
    SamplingCampaign — the full cross-context prerequisite chain Sprint
    8's ``RunPredictionCommand`` needs. Returns the assessment/selection/
    campaign ids."""
    create = client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Prediction Test", "hazard_type": "WILDFIRE"},
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

    burned_area = client.post(
        "/api/v1/predictor-variables",
        headers=headers,
        json={
            "name": "Burned Area Fraction",
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
    assert burned_area.status_code == 201, burned_area.text

    selection = client.post(
        "/api/v1/variable-selections",
        headers=headers,
        json={
            "name": "Wildfire prediction variables",
            "hazard_type": "WILDFIRE",
            "selected_variable_ids": [
                ndvi.json()["id"],
                wind.json()["id"],
                burned_area.json()["id"],
            ],
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
        json={"source": "DRAWN", "geometry": _SQUARE_GEOJSON, "name": "Prediction AOI"},
    )
    assert aoi.status_code == 201, aoi.text
    aoi_id = aoi.json()["id"]

    campaign = client.post(
        f"/api/v1/assessments/{assessment_id}/sampling-campaigns",
        headers=headers,
        json={
            "aoi_id": aoi_id,
            "name": "Prediction Campaign",
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

    return {
        "assessment_id": assessment_id,
        "variable_selection_id": selection_id,
        "sampling_campaign_id": campaign_id,
    }


@pytest.mark.parametrize(
    "method,expected_formula_version",
    [
        ("PEARSON_CORRELATION", "pearson-v1"),
        ("SPEARMAN_CORRELATION", "spearman-v1"),
        ("KENDALL_CORRELATION", "kendall-tau-b-v1"),
    ],
)
def test_run_correlation_prediction_via_http(
    api_client: TestClient, method: str, expected_formula_version: str
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers, tenant_id = _register_and_login_with_tenant(api_client, suffix)
    _seed_real_observations(tenant_id)
    ctx = _build_prediction_ready_assessment(api_client, headers)

    run = api_client.post(
        f"/api/v1/assessments/{ctx['assessment_id']}/predictions/actions/run",
        headers=headers,
        json={
            "variable_selection_id": ctx["variable_selection_id"],
            "sampling_campaign_id": ctx["sampling_campaign_id"],
            "method": method,
        },
    )
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["status"] == "COMPLETED"
    assert body["version"] == 1
    assert body["correlation_pairs"] is not None
    # 3 variables (ndvi, wind_speed, burned_area) -> 3 unordered pairs.
    assert len(body["correlation_pairs"]) == 3
    assert body["model_metadata"]["formula_version"] == expected_formula_version
    assert body["model_metadata"]["sample_size"] == _REAL_OBSERVATION_COUNT


def test_run_mlr_prediction_via_http(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers, tenant_id = _register_and_login_with_tenant(api_client, suffix)
    _seed_real_observations(tenant_id)
    ctx = _build_prediction_ready_assessment(api_client, headers)

    run = api_client.post(
        f"/api/v1/assessments/{ctx['assessment_id']}/predictions/actions/run",
        headers=headers,
        json={
            "variable_selection_id": ctx["variable_selection_id"],
            "sampling_campaign_id": ctx["sampling_campaign_id"],
            "method": "MULTIPLE_LINEAR_REGRESSION",
        },
    )
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["status"] == "COMPLETED"
    assert body["intercept"] is not None
    assert body["r_squared"] is not None
    assert body["adjusted_r_squared"] is not None
    assert body["rmse"] is not None
    assert body["mae"] is not None
    assert {v["code"] for v in body["variables"]} == {"ndvi", "wind_speed"}
    assert body["model_metadata"]["dependent_variable_code"] == "burned_area"
    assert body["model_metadata"]["formula_version"] == "mlr-ols-v1"

    fetched = api_client.get(
        f"/api/v1/assessments/{ctx['assessment_id']}/predictions/{body['id']}", headers=headers
    )
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]

    listing = api_client.get(
        f"/api/v1/assessments/{ctx['assessment_id']}/predictions", headers=headers
    )
    assert listing.status_code == 200
    assert len(listing.json()["data"]) == 1


def test_re_running_prediction_increments_version_via_http(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    ctx = _build_prediction_ready_assessment(api_client, headers)
    request_body = {
        "variable_selection_id": ctx["variable_selection_id"],
        "sampling_campaign_id": ctx["sampling_campaign_id"],
        "method": "PEARSON_CORRELATION",
    }

    first = api_client.post(
        f"/api/v1/assessments/{ctx['assessment_id']}/predictions/actions/run",
        headers=headers,
        json=request_body,
    )
    assert first.status_code == 201, first.text
    assert first.json()["version"] == 1

    second = api_client.post(
        f"/api/v1/assessments/{ctx['assessment_id']}/predictions/actions/run",
        headers=headers,
        json=request_body,
    )
    assert second.status_code == 201, second.text
    assert second.json()["version"] == 2


def test_run_prediction_with_unconfirmed_variable_selection_fails_via_http(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)

    create = api_client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Unconfirmed Selection Test", "hazard_type": "WILDFIRE"},
    )
    assessment_id = create.json()["id"]

    ndvi = api_client.post(
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
        },
    )
    selection = api_client.post(
        "/api/v1/variable-selections",
        headers=headers,
        json={
            "name": "Unconfirmed",
            "hazard_type": "WILDFIRE",
            "selected_variable_ids": [ndvi.json()["id"]],
        },
    )
    assert selection.json()["status"] == "DRAFT"

    aoi = api_client.post(
        f"/api/v1/assessments/{assessment_id}/aoi",
        headers=headers,
        json={"source": "DRAWN", "geometry": _SQUARE_GEOJSON, "name": "AOI"},
    )
    campaign = api_client.post(
        f"/api/v1/assessments/{assessment_id}/sampling-campaigns",
        headers=headers,
        json={
            "aoi_id": aoi.json()["id"],
            "name": "Campaign",
            "method": "SIMPLE_RANDOM",
            "sample_size": 1000,
        },
    )
    api_client.post(
        f"/api/v1/assessments/{assessment_id}/sampling-campaigns/{campaign.json()['id']}"
        "/actions/generate-points",
        headers=headers,
    )

    run = api_client.post(
        f"/api/v1/assessments/{assessment_id}/predictions/actions/run",
        headers=headers,
        json={
            "variable_selection_id": selection.json()["id"],
            "sampling_campaign_id": campaign.json()["id"],
            "method": "PEARSON_CORRELATION",
        },
    )
    assert run.status_code == 201, run.text
    assert run.json()["status"] == "FAILED"
    assert "CONFIRMED" in run.json()["error"]
