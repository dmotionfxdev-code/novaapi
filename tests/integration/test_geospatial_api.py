"""End-to-end HTTP tests for the Geospatial API against a real Postgres
instance — Identity + Assessment + Geospatial composed together, proving
the cross-context wiring works over real HTTP.
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
def api_client():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = Settings(
        database_url=database_url, jwt_secret_key="test-secret-key-for-geospatial-api-tests"
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        yield client


def _register_and_login(client: TestClient, suffix: str) -> dict:
    registration = client.post(
        "/api/v1/tenants",
        json={
            "name": f"Geospatial API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@geoapi.example",
            "owner_email": f"owner-{suffix}@geoapi.example",
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


def test_define_revise_and_list_aoi_versions_via_http(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)

    create = api_client.post(
        "/api/v1/assessments", headers=headers, json={"name": "AOI Test", "hazard_type": "FLOOD"}
    )
    assert create.status_code == 201, create.text
    assessment_id = create.json()["id"]

    define = api_client.post(
        f"/api/v1/assessments/{assessment_id}/aoi",
        headers=headers,
        json={"source": "DRAWN", "geometry": _SQUARE_GEOJSON, "name": "Initial AOI"},
    )
    assert define.status_code == 201, define.text
    assert define.json()["version"] == 1
    assert define.json()["status"] == "ACTIVE"
    assert define.json()["area_m2"] > 0

    revise = api_client.post(
        f"/api/v1/assessments/{assessment_id}/aoi",
        headers=headers,
        json={"source": "DRAWN", "geometry": _SQUARE_GEOJSON, "name": "Revised AOI"},
    )
    assert revise.status_code == 201, revise.text
    assert revise.json()["version"] == 2

    active = api_client.get(f"/api/v1/assessments/{assessment_id}/aoi", headers=headers)
    assert active.status_code == 200
    assert active.json()["version"] == 2
    assert active.json()["name"] == "Revised AOI"

    versions = api_client.get(
        f"/api/v1/assessments/{assessment_id}/aoi/versions", headers=headers
    )
    assert versions.status_code == 200
    assert [v["version"] for v in versions.json()["data"]] == [1, 2]


def test_configure_and_generate_sampling_campaign_via_http(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers = _register_and_login(api_client, suffix)

    create = api_client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Sampling Test", "hazard_type": "FLOOD"},
    )
    assessment_id = create.json()["id"]

    define = api_client.post(
        f"/api/v1/assessments/{assessment_id}/aoi",
        headers=headers,
        json={"source": "DRAWN", "geometry": _SQUARE_GEOJSON, "name": "AOI"},
    )
    aoi_id = define.json()["id"]

    configure = api_client.post(
        f"/api/v1/assessments/{assessment_id}/sampling-campaigns",
        headers=headers,
        json={
            "aoi_id": aoi_id,
            "name": "Campaign 1",
            "method": "SIMPLE_RANDOM",
            "sample_size": 1000,
        },
    )
    assert configure.status_code == 201, configure.text
    campaign_id = configure.json()["id"]
    assert configure.json()["status"] == "DRAFT"

    generate = api_client.post(
        f"/api/v1/assessments/{assessment_id}/sampling-campaigns/{campaign_id}"
        "/actions/generate-points",
        headers=headers,
    )
    assert generate.status_code == 200, generate.text
    assert generate.json()["status"] == "GENERATED"
    assert generate.json()["sample_count"] == 1000

    points = api_client.get(
        f"/api/v1/assessments/{assessment_id}/sampling-campaigns/{campaign_id}/points",
        headers=headers,
    )
    assert points.status_code == 200
    assert len(points.json()["data"]) == 1000
