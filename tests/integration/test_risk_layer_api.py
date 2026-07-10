"""Sprint C — end-to-end HTTP tests for the real spatial Risk Layer read
API (requirement #5's download endpoint) against a real Postgres
instance — Identity + Assessment + WorkflowTemplate + Workflow Engine +
Analysis (FIRAS) + Data Acquisition composed together exactly as
production ``api/app.py`` wires them, proving
``CompositionRootRiskLayerService`` genuinely auto-generates a real
GeoJSON risk layer during a real HTTP-driven workflow run, and that it's
downloadable afterward with zero manual regeneration step.
"""

from __future__ import annotations

import asyncio
import base64
import os
import uuid

import pytest
import shapefile as pyshp
from fastapi.testclient import TestClient

from georisk.api.app import create_app
from georisk.contexts.data_acquisition.application.commands import (
    ExecuteAcquisitionJobCommand,
    RegisterDatasetSourceCommand,
    ScheduleAcquisitionJobCommand,
)
from georisk.contexts.data_acquisition.application.handlers import (
    ExecuteAcquisitionJobHandler,
    RegisterDatasetSourceHandler,
    ScheduleAcquisitionJobHandler,
)
from georisk.contexts.data_acquisition.application.ports import (
    LocalUploadProvider,
    ProviderRegistry,
)
from georisk.contexts.data_acquisition.domain.value_objects import (
    AcquisitionJobStatus,
    DataProvider,
)
from georisk.db.session import Database
from georisk.settings import Settings
from tests.integration._sprint_a_seed_helpers import seed_firas_indicator_datasets_sync

pytestmark = pytest.mark.integration

_WGS84_PRJ = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
)


@pytest.fixture
def api_client():  # noqa: ANN201
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL not set — integration tests need a real Postgres instance")
    settings = Settings(
        database_url=database_url, jwt_secret_key="test-secret-key-for-risk-layer-api-tests"
    )
    app = create_app(settings=settings)
    with TestClient(app) as client:
        yield client


def _register_and_login_with_tenant(client: TestClient, suffix: str) -> tuple[dict, str]:
    registration = client.post(
        "/api/v1/tenants",
        json={
            "name": f"Risk Layer API Test Co {suffix}",
            "tenant_email": f"contact-{suffix}@risklayerapi.example",
            "owner_email": f"owner-{suffix}@risklayerapi.example",
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
            "name": f"Risk Layer API Template {suffix}",
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
    template_id = create.json()["id"]
    publish = client.post(
        f"/api/v1/workflow-templates/{template_id}/actions/publish", headers=headers
    )
    assert publish.status_code == 200, publish.text
    return template_id


def _polygon_shapefile_zip() -> bytes:
    import io
    import zipfile

    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = pyshp.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=pyshp.POLYGON)
    writer.field("name", "C", size=40)
    writer.field("area_ha", "N", decimal=2)
    writer.poly([[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]])
    writer.record("Field A", 12.5)
    writer.poly([[[20, 20], [20, 30], [30, 30], [30, 20], [20, 20]]])
    writer.record("Field B", 8.25)
    writer.close()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("parcels.shp", shp.getvalue())
        archive.writestr("parcels.shx", shx.getvalue())
        archive.writestr("parcels.dbf", dbf.getvalue())
        archive.writestr("parcels.prj", _WGS84_PRJ)
    return buf.getvalue()


async def _seed_risk_geometry(database_url: str, tenant_id: str) -> None:
    db = Database(database_url)
    try:
        async with db.session() as session:
            source = await RegisterDatasetSourceHandler(session).handle(
                RegisterDatasetSourceCommand(
                    tenant_id=tenant_id,
                    name="Risk Layer Geometry Upload",
                    provider="LOCAL_UPLOAD",
                    description="",
                    issued_by="analyst-1",
                )
            )
        async with db.session() as session:
            job = await ScheduleAcquisitionJobHandler(session).handle(
                ScheduleAcquisitionJobCommand(
                    tenant_id=tenant_id,
                    provider="LOCAL_UPLOAD",
                    source_reference="FLOOD:RISK",
                    format="SHAPEFILE",
                    dataset_source_id=str(source.id),
                    declared_crs="EPSG:4326",
                    raw_content_base64=base64.b64encode(_polygon_shapefile_zip()).decode(),
                    issued_by="analyst-1",
                )
            )
        registry = ProviderRegistry()
        registry.register(DataProvider.LOCAL_UPLOAD, LocalUploadProvider())

        class _NullAoiReader:
            async def get_aoi_geometry(self, *, tenant_id, aoi_id):  # noqa: ANN001
                raise AssertionError("not expected")

        async with db.session() as session:
            completed = await ExecuteAcquisitionJobHandler(
                session, registry, _NullAoiReader()
            ).handle(
                ExecuteAcquisitionJobCommand(
                    tenant_id=tenant_id, acquisition_job_id=str(job.id), issued_by="analyst-1"
                )
            )
        assert completed.status == AcquisitionJobStatus.COMPLETED, completed.error
    finally:
        await db.dispose()


def _seed_risk_geometry_sync(database_url: str, tenant_id: str) -> None:
    asyncio.run(_seed_risk_geometry(database_url, tenant_id))


def test_risk_layer_geojson_download_endpoint_after_real_workflow_run(
    api_client: TestClient,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers, tenant_id = _register_and_login_with_tenant(api_client, suffix)
    seed_firas_indicator_datasets_sync(os.environ["DATABASE_URL"], tenant_id)
    _seed_risk_geometry_sync(os.environ["DATABASE_URL"], tenant_id)
    template_id = _create_and_publish_firas_template(api_client, headers, suffix)

    create = api_client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "Risk Layer Download Test", "hazard_type": "FLOOD"},
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

    # --- Metadata endpoint ---
    metadata = api_client.get(f"/api/v1/assessments/{assessment_id}/risk-layer", headers=headers)
    assert metadata.status_code == 200, metadata.text
    body = metadata.json()
    assert body["hazard_type"] == "FLOOD"
    assert body["stage_type"] == "RISK"
    assert body["geometry_type"] == "Polygon"
    assert body["feature_count"] == 2
    assert body["crs"] == "EPSG:4326"
    assert body["risk_index"] == pytest.approx(0.1101, abs=1e-4)
    assert body["risk_level"] == "LOW"
    assert body["raster_metadata"]["available"] is False

    # --- Download endpoint (the real GeoJSON) ---
    geojson_response = api_client.get(
        f"/api/v1/assessments/{assessment_id}/risk-layer.geojson", headers=headers
    )
    assert geojson_response.status_code == 200, geojson_response.text
    assert geojson_response.headers["content-type"].startswith("application/geo+json")
    geojson = geojson_response.json()
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 2
    feature_names = {f["properties"]["source_attributes"]["name"] for f in geojson["features"]}
    assert feature_names == {"Field A", "Field B"}
    for feature in geojson["features"]:
        assert feature["properties"]["risk_index"] == pytest.approx(0.1101, abs=1e-4)
        assert feature["properties"]["dataset_id"]
        assert feature["geometry"]["type"] == "Polygon"

    # --- Risk summary endpoint (non-spatial companion) ---
    summary = api_client.get(f"/api/v1/assessments/{assessment_id}/risk-summary", headers=headers)
    assert summary.status_code == 200, summary.text
    summary_body = summary.json()
    assert summary_body["risk_index"] == pytest.approx(0.1101, abs=1e-4)
    assert summary_body["classification"] == "Low Risk"
    assert "features" not in summary_body


def test_risk_layer_not_found_before_analysis_runs(api_client: TestClient) -> None:
    suffix = uuid.uuid4().hex[:8]
    headers, _tenant_id = _register_and_login_with_tenant(api_client, suffix)

    create = api_client.post(
        "/api/v1/assessments",
        headers=headers,
        json={"name": "No Risk Layer Yet", "hazard_type": "FLOOD"},
    )
    assessment_id = create.json()["id"]

    response = api_client.get(f"/api/v1/assessments/{assessment_id}/risk-layer", headers=headers)
    assert response.status_code == 404
