"""End-to-end HTTP tests for the Data Acquisition API against a real
Postgres instance.
"""

from __future__ import annotations

import base64
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
        database_url=database_url,
        jwt_secret_key="test-secret-key-for-data-acquisition-api-tests",
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        yield client


def _register_and_login(client: TestClient, suffix: str) -> dict:
    registration = client.post(
        "/api/v1/tenants",
        json={
            "name": f"Dataset API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@datasetapi.example",
            "owner_email": f"owner-{suffix}@datasetapi.example",
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


def test_register_source_catalog_and_revise_dataset_via_http(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)

    source = api_client.post(
        "/api/v1/dataset-sources",
        headers=headers,
        json={"name": "CHIRPS", "provider": "CHIRPS", "description": "Rainfall estimates"},
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]

    catalog = api_client.post(
        "/api/v1/datasets",
        headers=headers,
        json={
            "dataset_source_id": source_id,
            "name": "Rainfall-2020-2025",
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
    assert catalog.json()["version"] == 1
    assert catalog.json()["readiness"] == ["MLR_READY"]

    revise = api_client.post(
        "/api/v1/datasets/by-name/Rainfall-2020-2025/actions/revise",
        headers=headers,
        json={
            "dataset_type": "RASTER",
            "source": "Satellite",
            "provider": "CHIRPS",
            "acquisition_date": "2026-02-01",
            "crs": "EPSG:4326",
            "spatial_coverage": "Tanzania",
            "temporal_coverage_start": "2020-01-01T00:00:00Z",
            "temporal_coverage_end": "2026-01-31T00:00:00Z",
            "processing_method": "CLOUD_MASKED",
            "description": "Reprocessed with cloud masking",
            "is_mlr_ready": True,
        },
    )
    assert revise.status_code == 200, revise.text
    assert revise.json()["version"] == 2
    assert len(revise.json()["provenance"]) == 2

    catalog_list = api_client.get(
        "/api/v1/datasets", headers=headers, params={"mlr_ready": True}
    )
    assert catalog_list.status_code == 200
    assert len(catalog_list.json()["data"]) == 1
    assert catalog_list.json()["data"][0]["version"] == 2

    versions = api_client.get(
        "/api/v1/datasets/by-name/Rainfall-2020-2025/versions", headers=headers
    )
    assert versions.status_code == 200
    assert [v["version"] for v in versions.json()["data"]] == [1, 2]


def test_register_predictor_variables_and_confirm_selection_via_http(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)

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
    assert ndvi.status_code == 201, ndvi.text

    wind = api_client.post(
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
        },
    )
    assert wind.status_code == 201, wind.text

    variables = api_client.get("/api/v1/predictor-variables", headers=headers)
    assert variables.status_code == 200
    assert len(variables.json()["data"]) == 2

    selection = api_client.post(
        "/api/v1/variable-selections",
        headers=headers,
        json={
            "name": "WRRAS core variables",
            "hazard_type": "WILDFIRE",
            "selected_variable_ids": [ndvi.json()["id"], wind.json()["id"]],
        },
    )
    assert selection.status_code == 201, selection.text
    selection_id = selection.json()["id"]
    assert selection.json()["status"] == "DRAFT"

    confirm = api_client.post(
        f"/api/v1/variable-selections/{selection_id}/actions/confirm", headers=headers
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["status"] == "CONFIRMED"


def test_schedule_and_execute_local_upload_acquisition_job_via_http(
    api_client: TestClient,
) -> None:
    """End-to-end exercise of Sprint 13's Dataset Import Pipeline over
    real HTTP against the real app-wired ``ProviderRegistry`` — Local
    Upload needs no external network, so this is the one provider this
    sandboxed validation environment can genuinely exercise end-to-end.
    """
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)

    source = api_client.post(
        "/api/v1/dataset-sources",
        headers=headers,
        json={
            "name": "Local Upload Source",
            "provider": "LOCAL_UPLOAD",
            "description": "Manually uploaded files",
        },
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]

    csv_content = b"station,rainfall_mm\nA,12.5\nB,8.3\n"
    schedule = api_client.post(
        "/api/v1/acquisition-jobs",
        headers=headers,
        json={
            "provider": "LOCAL_UPLOAD",
            "source_reference": "station-rainfall.csv",
            "format": "CSV",
            "dataset_source_id": source_id,
            "declared_crs": "EPSG:4326",
            "raw_content_base64": base64.b64encode(csv_content).decode(),
        },
    )
    assert schedule.status_code == 201, schedule.text
    job_id = schedule.json()["id"]
    assert schedule.json()["status"] == "SCHEDULED"

    fetched = api_client.get(f"/api/v1/acquisition-jobs/{job_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "SCHEDULED"

    execute = api_client.post(
        f"/api/v1/acquisition-jobs/{job_id}/actions/execute", headers=headers
    )
    assert execute.status_code == 200, execute.text
    assert execute.json()["status"] == "COMPLETED"
    assert execute.json()["dataset_id"] is not None

    listed = api_client.get("/api/v1/acquisition-jobs", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 1
    assert listed.json()["data"][0]["status"] == "COMPLETED"

    dataset = api_client.get(f"/api/v1/datasets/{execute.json()['dataset_id']}", headers=headers)
    assert dataset.status_code == 200, dataset.text
    assert dataset.json()["provider"] == "LOCAL_UPLOAD"


def test_schedule_acquisition_job_rejects_non_acquisition_capable_provider_via_http(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)

    source = api_client.post(
        "/api/v1/dataset-sources",
        headers=headers,
        json={"name": "CHIRPS", "provider": "CHIRPS", "description": ""},
    )
    assert source.status_code == 201, source.text

    schedule = api_client.post(
        "/api/v1/acquisition-jobs",
        headers=headers,
        json={
            "provider": "CHIRPS",
            "source_reference": "chirps-daily",
            "format": "CSV",
            "dataset_source_id": source.json()["id"],
            "declared_crs": "EPSG:4326",
        },
    )
    assert schedule.status_code == 400, schedule.text


def test_schedule_gee_job_requires_remote_sensing_source_and_aoi_via_http(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)

    source = api_client.post(
        "/api/v1/dataset-sources",
        headers=headers,
        json={"name": "GEE Source", "provider": "GOOGLE_EARTH_ENGINE", "description": ""},
    )
    assert source.status_code == 201, source.text
    source_id = source.json()["id"]

    missing_remote_sensing_source = api_client.post(
        "/api/v1/acquisition-jobs",
        headers=headers,
        json={
            "provider": "GOOGLE_EARTH_ENGINE",
            "source_reference": "sentinel-2-composite",
            "format": "GEOTIFF",
            "dataset_source_id": source_id,
            "declared_crs": "EPSG:4326",
            "aoi_id": "some-aoi",
        },
    )
    assert missing_remote_sensing_source.status_code == 400, missing_remote_sensing_source.text

    missing_aoi = api_client.post(
        "/api/v1/acquisition-jobs",
        headers=headers,
        json={
            "provider": "GOOGLE_EARTH_ENGINE",
            "source_reference": "sentinel-2-composite",
            "format": "GEOTIFF",
            "dataset_source_id": source_id,
            "declared_crs": "EPSG:4326",
            "remote_sensing_source": "SENTINEL_2",
        },
    )
    assert missing_aoi.status_code == 400, missing_aoi.text


def test_execute_gee_job_resolves_real_aoi_then_fails_honestly_when_gee_unconfigured(
    api_client: TestClient,
) -> None:
    """Proves Sprint 14's AOI-based Processing composition root
    (``CompositionRootAoiReader``) genuinely resolves a real Geospatial
    ``AreaOfInterest`` over HTTP — the job fails with GEE's own "not
    configured" message (this sandboxed environment has no real GEE
    service account), NOT an "AreaOfInterest not found" error, which is
    exactly the signal that AOI resolution itself succeeded before the
    (expected, honest) GEE failure.
    """
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)
    assessment_id = str(uuid.uuid4())  # assessment_id is stored as a UUID column

    aoi = api_client.post(
        f"/api/v1/assessments/{assessment_id}/aoi",
        headers=headers,
        json={
            "source": "DRAWN",
            "name": "GEE smoke test AOI",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
            },
        },
    )
    assert aoi.status_code == 201, aoi.text
    aoi_id = aoi.json()["id"]

    source = api_client.post(
        "/api/v1/dataset-sources",
        headers=headers,
        json={"name": "GEE Source", "provider": "GOOGLE_EARTH_ENGINE", "description": ""},
    )
    assert source.status_code == 201, source.text

    schedule = api_client.post(
        "/api/v1/acquisition-jobs",
        headers=headers,
        json={
            "provider": "GOOGLE_EARTH_ENGINE",
            "source_reference": "sentinel-2-composite",
            "format": "GEOTIFF",
            "dataset_source_id": source.json()["id"],
            "declared_crs": "EPSG:4326",
            "remote_sensing_source": "SENTINEL_2",
            "aoi_id": aoi_id,
            "requested_indices": ["NDVI"],
        },
    )
    assert schedule.status_code == 201, schedule.text
    job_id = schedule.json()["id"]

    execute = api_client.post(
        f"/api/v1/acquisition-jobs/{job_id}/actions/execute", headers=headers
    )
    assert execute.status_code == 200, execute.text
    assert execute.json()["status"] == "FAILED"
    assert "not configured" in execute.json()["error"]
