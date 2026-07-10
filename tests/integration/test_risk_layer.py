"""Sprint C — Risk Layer Generation & Spatial Visualization, against a
real Postgres instance. Reuses Sprint B's real ``pyshp``-built Shapefile
fixtures/upload-pipeline helpers (``test_shapefile_import.py``) and
Sprint A's real indicator-dataset seed helpers
(``_sprint_a_seed_helpers.py``) to drive an ACTUAL FIRAS/WRRAS workflow
through to a real RISK ``StageResult``, then verifies the auto-generated
``RiskLayer`` is built from the SAME genuinely-uploaded geometries — no
fabrication anywhere in the chain.

Uses ``real_database`` (not ``db_session``): ``AnalysisStageExecutor``/
``CompositionRootRiskLayerService``/``ExecuteAcquisitionJobHandler`` (via
its own session-per-call pattern) all need a real, independently-
connecting ``Database`` — the same reasoning every prior sprint's
analysis-integration test already established.
"""

from __future__ import annotations

import base64
import uuid

import pytest
import shapefile as pyshp

from georisk.api.analysis_ports import CompositionRootIndicatorInputProvider
from georisk.api.risk_layer_ports import CompositionRootRiskLayerService
from georisk.api.workflow_stage_executors import AnalysisStageExecutor
from georisk.contexts.analysis.application.strategy_registry import StrategyRegistry
from georisk.contexts.analysis.domain.errors import RiskLayerNotFoundError
from georisk.contexts.analysis.domain.value_objects import HazardType as AnalysisHazardType
from georisk.contexts.analysis.domain.value_objects import StageType as AnalysisStageType
from georisk.contexts.analysis.infrastructure.repositories import SqlAlchemyRiskLayerRepository
from georisk.contexts.analysis.strategies.firas.strategy import FIRASHazardStrategy
from georisk.contexts.analysis.strategies.wrras.strategy import WRRASHazardStrategy
from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.value_objects import HazardType as AssessmentHazardType
from georisk.contexts.assessment.domain.workflow_value_objects import (
    StageType as AssessmentStageType,
)
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
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
from georisk.contexts.data_acquisition.domain.value_objects import AcquisitionJobStatus
from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.db.session import Database
from tests.integration._sprint_a_seed_helpers import (
    seed_firas_indicator_datasets,
    seed_wrras_indicator_datasets,
)
from tests.integration.test_shapefile_import import (
    _WGS84_PRJ,
    _local_upload_registry,
    _multipolygon_shapefile_zip,
    _NullAoiReader,
    _point_shapefile_zip,
    _polygon_shapefile_zip,
    _shp_shx_dbf,
    _zip_archive,
)

pytestmark = pytest.mark.integration

_WEB_MERCATOR_PRJ = (
    'PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563]],PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433]],PROJECTION["Mercator_1SP"],'
    'PARAMETER["central_meridian",0],PARAMETER["scale_factor",1],'
    'PARAMETER["false_easting",0],PARAMETER["false_northing",0],'
    'UNIT["metre",1],AXIS["Easting",EAST],AXIS["Northing",NORTH]]'
)


async def _register_source(db: Database, tenant_id: TenantId) -> str:
    async with db.session() as session:
        source = await RegisterDatasetSourceHandler(session).handle(
            RegisterDatasetSourceCommand(
                tenant_id=str(tenant_id),
                name="Risk Layer Geometry Upload",
                provider="LOCAL_UPLOAD",
                description="",
                issued_by="analyst-1",
            )
        )
        return str(source.id)


async def _catalog_risk_geometry(
    db: Database, tenant_id: TenantId, *, hazard_type: str, zip_bytes: bytes
):
    """Uploads+catalogs a real Shapefile under the ``f"{hazard_type}:RISK"``
    naming convention ``CompositionRootRiskLayerService`` looks up —
    returns the completed ``AcquisitionJob``."""
    source_id = await _register_source(db, tenant_id)
    async with db.session() as session:
        job = await ScheduleAcquisitionJobHandler(session).handle(
            ScheduleAcquisitionJobCommand(
                tenant_id=str(tenant_id),
                provider="LOCAL_UPLOAD",
                source_reference=f"{hazard_type}:RISK",
                format="SHAPEFILE",
                dataset_source_id=source_id,
                declared_crs="EPSG:4326",
                raw_content_base64=base64.b64encode(zip_bytes).decode(),
                issued_by="analyst-1",
            )
        )
    async with db.session() as session:
        completed = await ExecuteAcquisitionJobHandler(
            session, _local_upload_registry(), _NullAoiReader()
        ).handle(
            ExecuteAcquisitionJobCommand(
                tenant_id=str(tenant_id), acquisition_job_id=str(job.id), issued_by="analyst-1"
            )
        )
    return completed


async def _create_assessment(
    db: Database, tenant_id: TenantId, hazard_type: AssessmentHazardType
) -> Assessment:
    async with db.session() as session:
        assessment, _ = Assessment.create(
            tenant_id=tenant_id,
            name=f"Risk Layer Test {uuid.uuid4().hex[:8]}",
            hazard_type=hazard_type,
            created_by=UserId.new(),
        )
        assessment.mark_ready(changed_by="tester")
        await SqlAlchemyAssessmentRepository(session).save(assessment)
        await session.commit()
    return assessment


def _firas_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(AnalysisHazardType.FLOOD, FIRASHazardStrategy())
    return registry


def _wrras_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(AnalysisHazardType.WILDFIRE, WRRASHazardStrategy())
    return registry


def _executor(db: Database, registry: StrategyRegistry) -> AnalysisStageExecutor:
    return AnalysisStageExecutor(
        db,
        registry,
        CompositionRootIndicatorInputProvider(db),
        CompositionRootRiskLayerService(db),
    )


async def _run_to_risk(
    db: Database, executor: AnalysisStageExecutor, assessment_id: str
) -> None:
    for stage in (
        AssessmentStageType.HAZARD,
        AssessmentStageType.EXPOSURE,
        AssessmentStageType.VULNERABILITY,
        AssessmentStageType.RISK,
    ):
        outcome = await executor.execute(stage, assessment_id=assessment_id)
        assert outcome.success, f"{stage}: {outcome.error}"


# --- FIRAS / WRRAS -> real GeoJSON risk layer ---


async def test_firas_workflow_generates_real_geojson_risk_layer(real_database: Database) -> None:
    tenant_id = TenantId.new()
    await seed_firas_indicator_datasets(real_database, tenant_id)
    await _catalog_risk_geometry(
        real_database, tenant_id, hazard_type="FLOOD", zip_bytes=_polygon_shapefile_zip()
    )
    assessment = await _create_assessment(real_database, tenant_id, AssessmentHazardType.FLOOD)
    executor = _executor(real_database, _firas_registry())
    await _run_to_risk(real_database, executor, str(assessment.id))

    async with real_database.session() as session:
        layer = await SqlAlchemyRiskLayerRepository(session).get_latest(
            tenant_id, str(assessment.id), AnalysisStageType.RISK
        )
    assert layer is not None
    assert layer.hazard_type is AnalysisHazardType.FLOOD
    assert layer.geometry_type == "Polygon"
    assert layer.feature_count == 2
    assert layer.risk_index == pytest.approx(0.1101, abs=1e-4)
    assert layer.risk_level == "LOW"
    assert layer.formula_version == "fri-multiplicative-v2"
    assert layer.geojson["type"] == "FeatureCollection"
    assert len(layer.geojson["features"]) == 2
    for feature in layer.geojson["features"]:
        assert feature["properties"]["risk_index"] == pytest.approx(0.1101, abs=1e-4)
        assert feature["properties"]["flood_risk_index"] == pytest.approx(0.1101, abs=1e-4)


async def test_wrras_workflow_generates_real_geojson_risk_layer(real_database: Database) -> None:
    tenant_id = TenantId.new()
    await seed_wrras_indicator_datasets(real_database, tenant_id)
    await _catalog_risk_geometry(
        real_database, tenant_id, hazard_type="WILDFIRE", zip_bytes=_point_shapefile_zip()
    )
    assessment = await _create_assessment(real_database, tenant_id, AssessmentHazardType.WILDFIRE)
    executor = _executor(real_database, _wrras_registry())
    await _run_to_risk(real_database, executor, str(assessment.id))

    async with real_database.session() as session:
        layer = await SqlAlchemyRiskLayerRepository(session).get_latest(
            tenant_id, str(assessment.id), AnalysisStageType.RISK
        )
    assert layer is not None
    assert layer.hazard_type is AnalysisHazardType.WILDFIRE
    assert layer.geometry_type == "Point"
    assert layer.feature_count == 2
    assert layer.risk_index == pytest.approx(0.0926, abs=1e-4)
    assert layer.formula_version == "wri-multiplicative-v1"


# --- Geometry types ---


async def test_multipolygon_dataset_produces_multipolygon_risk_layer(
    real_database: Database,
) -> None:
    tenant_id = TenantId.new()
    await seed_firas_indicator_datasets(real_database, tenant_id)
    await _catalog_risk_geometry(
        real_database, tenant_id, hazard_type="FLOOD", zip_bytes=_multipolygon_shapefile_zip()
    )
    assessment = await _create_assessment(real_database, tenant_id, AssessmentHazardType.FLOOD)
    executor = _executor(real_database, _firas_registry())
    await _run_to_risk(real_database, executor, str(assessment.id))

    async with real_database.session() as session:
        layer = await SqlAlchemyRiskLayerRepository(session).get_latest(
            tenant_id, str(assessment.id), AnalysisStageType.RISK
        )
    assert layer is not None
    assert layer.geometry_type == "MultiPolygon"
    assert layer.feature_count == 1
    assert layer.geojson["features"][0]["geometry"]["type"] == "MultiPolygon"


async def test_point_dataset_produces_point_risk_layer(real_database: Database) -> None:
    tenant_id = TenantId.new()
    await seed_wrras_indicator_datasets(real_database, tenant_id)
    await _catalog_risk_geometry(
        real_database, tenant_id, hazard_type="WILDFIRE", zip_bytes=_point_shapefile_zip()
    )
    assessment = await _create_assessment(real_database, tenant_id, AssessmentHazardType.WILDFIRE)
    executor = _executor(real_database, _wrras_registry())
    await _run_to_risk(real_database, executor, str(assessment.id))

    async with real_database.session() as session:
        layer = await SqlAlchemyRiskLayerRepository(session).get_latest(
            tenant_id, str(assessment.id), AnalysisStageType.RISK
        )
    assert layer is not None
    assert layer.geometry_type == "Point"
    for feature in layer.geojson["features"]:
        assert feature["geometry"]["type"] == "Point"


# --- CRS preservation ---


async def test_crs_is_preserved_not_silently_forced_to_wgs84(real_database: Database) -> None:
    tenant_id = TenantId.new()
    await seed_firas_indicator_datasets(real_database, tenant_id)

    parts = _shp_shx_dbf(
        shape_type=pyshp.POLYGON,
        fields=[("name", "C", 0)],
        rows=[([[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]], ("Zone A",))],
    )
    zip_bytes = _zip_archive(
        "mercator",
        {
            "shp": parts["shp"],
            "shx": parts["shx"],
            "dbf": parts["dbf"],
            "prj": _WEB_MERCATOR_PRJ.encode(),
        },
    )
    completed = await _catalog_risk_geometry(
        real_database, tenant_id, hazard_type="FLOOD", zip_bytes=zip_bytes
    )
    assert completed.status == AcquisitionJobStatus.COMPLETED, completed.error
    assert completed.shapefile_crs != "EPSG:4326"  # confirms the fixture is genuinely non-4326

    assessment = await _create_assessment(real_database, tenant_id, AssessmentHazardType.FLOOD)
    executor = _executor(real_database, _firas_registry())
    await _run_to_risk(real_database, executor, str(assessment.id))

    async with real_database.session() as session:
        layer = await SqlAlchemyRiskLayerRepository(session).get_latest(
            tenant_id, str(assessment.id), AnalysisStageType.RISK
        )
    assert layer is not None
    # Preserved exactly as declared by the uploaded .prj — never silently
    # reprojected/overwritten to EPSG:4326.
    assert layer.crs == completed.shapefile_crs


# --- Attribute preservation ---


async def test_source_attributes_are_preserved_on_every_feature(real_database: Database) -> None:
    tenant_id = TenantId.new()
    await seed_firas_indicator_datasets(real_database, tenant_id)
    await _catalog_risk_geometry(
        real_database, tenant_id, hazard_type="FLOOD", zip_bytes=_polygon_shapefile_zip()
    )
    assessment = await _create_assessment(real_database, tenant_id, AssessmentHazardType.FLOOD)
    executor = _executor(real_database, _firas_registry())
    await _run_to_risk(real_database, executor, str(assessment.id))

    async with real_database.session() as session:
        layer = await SqlAlchemyRiskLayerRepository(session).get_latest(
            tenant_id, str(assessment.id), AnalysisStageType.RISK
        )
    assert layer is not None
    source_attrs = [f["properties"]["source_attributes"] for f in layer.geojson["features"]]
    assert {"name": "Field A", "area_ha": 12.5} in source_attrs
    assert {"name": "Field B", "area_ha": 8.25} in source_attrs


# --- Empty dataset rejection ---


async def test_empty_geometry_dataset_is_rejected_and_no_risk_layer_generated(
    real_database: Database,
) -> None:
    tenant_id = TenantId.new()
    await seed_firas_indicator_datasets(real_database, tenant_id)

    parts = _shp_shx_dbf(
        shape_type=pyshp.POLYGON, fields=[("name", "C", 0)], rows=[]
    )
    empty_zip = _zip_archive(
        "empty",
        {"shp": parts["shp"], "shx": parts["shx"], "dbf": parts["dbf"], "prj": _WGS84_PRJ.encode()},
    )
    failed_job = await _catalog_risk_geometry(
        real_database, tenant_id, hazard_type="FLOOD", zip_bytes=empty_zip
    )
    assert failed_job.status == AcquisitionJobStatus.FAILED
    assert failed_job.dataset_id is None

    assessment = await _create_assessment(real_database, tenant_id, AssessmentHazardType.FLOOD)
    # The RISK computation itself still succeeds (FIRAS/WRRAS's own math
    # doesn't depend on a geometry source existing) — only the auxiliary
    # spatial artifact is (correctly) never generated.
    executor = _executor(real_database, _firas_registry())
    await _run_to_risk(real_database, executor, str(assessment.id))

    async with real_database.session() as session:
        layer = await SqlAlchemyRiskLayerRepository(session).get_latest(
            tenant_id, str(assessment.id), AnalysisStageType.RISK
        )
    assert layer is None

    from georisk.contexts.analysis.application.queries import GetLatestRiskLayerQuery

    async with real_database.session() as session:
        with pytest.raises(RiskLayerNotFoundError):
            await GetLatestRiskLayerQuery(session).handle(tenant_id, str(assessment.id))


# --- End to end: Upload -> Import -> Analysis -> Risk Layer ---


async def test_end_to_end_upload_import_analysis_risk_layer(real_database: Database) -> None:
    tenant_id = TenantId.new()

    # Upload + Import (Sprint B, real pipeline).
    await seed_firas_indicator_datasets(real_database, tenant_id)
    completed_job = await _catalog_risk_geometry(
        real_database, tenant_id, hazard_type="FLOOD", zip_bytes=_polygon_shapefile_zip()
    )
    assert completed_job.status == AcquisitionJobStatus.COMPLETED

    # Analysis (Sprint A, real pipeline) -> Risk Layer (Sprint C, automatic).
    assessment = await _create_assessment(real_database, tenant_id, AssessmentHazardType.FLOOD)
    executor = _executor(real_database, _firas_registry())
    await _run_to_risk(real_database, executor, str(assessment.id))

    async with real_database.session() as session:
        layer = await SqlAlchemyRiskLayerRepository(session).get_latest(
            tenant_id, str(assessment.id), AnalysisStageType.RISK
        )
    assert layer is not None
    assert layer.dataset_id == str(completed_job.dataset_id)
    assert layer.feature_count == completed_job.shapefile_feature_count
    assert layer.geometry_type == completed_job.shapefile_geometry_type
    # Every feature's geometry is one of the genuinely uploaded ones —
    # never fabricated.
    uploaded_names = {"Field A", "Field B"}
    layer_names = {
        f["properties"]["source_attributes"]["name"] for f in layer.geojson["features"]
    }
    assert layer_names == uploaded_names
