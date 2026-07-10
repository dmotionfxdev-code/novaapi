"""Sprint B — real ESRI Shapefile ingestion, against a real Postgres
instance. Builds genuine Shapefile bytes with ``pyshp`` (test-fixture
generation only — never used by production code, which reads via
``pyogrio``/``shapely`` in ``infrastructure/shapefile_importer.py``), zips
them exactly like a real upload would arrive, and drives them through the
REAL ``ExecuteAcquisitionJobHandler`` pipeline — no shortcuts, no faked
validation outcomes.
"""

from __future__ import annotations

import base64
import io
import uuid
import zipfile

import pytest
import shapefile as pyshp

from georisk.api.analysis_ports import CompositionRootIndicatorInputProvider
from georisk.api.workflow_stage_executors import AnalysisStageExecutor
from georisk.contexts.analysis.application.strategy_registry import StrategyRegistry
from georisk.contexts.analysis.domain.value_objects import HazardType as AnalysisHazardType
from georisk.contexts.analysis.domain.value_objects import StageResultStatus
from georisk.contexts.analysis.domain.value_objects import StageType as AnalysisStageType
from georisk.contexts.analysis.infrastructure.repositories import SqlAlchemyStageResultRepository
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
from georisk.contexts.data_acquisition.application.ports import (
    LocalUploadProvider,
    ProviderRegistry,
)
from georisk.contexts.data_acquisition.domain.value_objects import (
    AcquisitionJobStatus,
    DataProvider,
    DatasetStatus,
)
from georisk.contexts.data_acquisition.infrastructure.repositories import (
    SqlAlchemyDatasetRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.db.session import Database

pytestmark = pytest.mark.integration

# --- Sprint A/B integration: WRRAS's BURN_SEVERITY stage is a leaf stage
# (no prior-StageResult dependency) whose exact 6 raw indicator codes
# (``nir_pre``/``swir_pre``/``nir_post``/``swir_post``/``red_pre``/
# ``red_post``) all fit within a classic DBF field name's 10-character
# limit — so a Shapefile's attribute table can name them EXACTLY, with no
# truncation/renaming, unlike FIRAS's/WRRAS's other stages whose codes
# (e.g. ``rainfall_index``, 14 chars) exceed that limit. Chosen for this
# specific reason: it proves requirement #8's real end-to-end wiring
# honestly, without inventing an unrequested field-name-aliasing layer.
_BURN_SEVERITY_FIELDS = [
    ("nir_pre", "N", 4),
    ("swir_pre", "N", 4),
    ("nir_post", "N", 4),
    ("swir_post", "N", 4),
    ("red_pre", "N", 4),
    ("red_post", "N", 4),
]
_BURN_SEVERITY_VALUES = {
    "nir_pre": 0.45,
    "swir_pre": 0.20,
    "nir_post": 0.25,
    "swir_post": 0.30,
    "red_pre": 0.08,
    "red_post": 0.18,
}

_WGS84_PRJ = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
)


def _local_upload_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(DataProvider.LOCAL_UPLOAD, LocalUploadProvider())
    return registry


class _NullAoiReader:
    async def get_aoi_geometry(self, *, tenant_id, aoi_id):  # noqa: ANN001
        raise AssertionError("AoiReader should not be called for a Shapefile job (no aoi_id)")


def _shp_shx_dbf(
    *, shape_type: int, fields: list[tuple[str, str, int]], rows: list[tuple]
) -> dict[str, bytes]:
    """Genuinely writes Shapefile bytes via ``pyshp`` — each ``rows``
    entry is ``(coords, record_values)``; ``coords`` is a single point
    ``(x, y)`` for ``POINT``, or a list of rings for ``POLYGON``. Each
    ``fields`` entry is ``(name, dbf_type_code, decimal_places)`` —
    ``decimal_places`` matters: pyshp's numeric ("N") field defaults to
    ZERO decimal places, silently truncating any float value to an
    integer if not given explicitly (found only by actually running these
    fixtures, not assumed)."""
    shp_buf, shx_buf, dbf_buf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = pyshp.Writer(shp=shp_buf, shx=shx_buf, dbf=dbf_buf, shapeType=shape_type)
    for name, type_code, decimal in fields:
        writer.field(name, type_code, decimal=decimal)
    for coords, record in rows:
        if shape_type == pyshp.POINT:
            writer.point(*coords)
        else:
            writer.poly(coords)
        writer.record(*record)
    writer.close()
    return {"shp": shp_buf.getvalue(), "shx": shx_buf.getvalue(), "dbf": dbf_buf.getvalue()}


def _zip_archive(base_name: str, components: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for ext, content in components.items():
            archive.writestr(f"{base_name}.{ext}", content)
    return buf.getvalue()


def _point_shapefile_zip(base_name: str = "stations") -> bytes:
    parts = _shp_shx_dbf(
        shape_type=pyshp.POINT,
        fields=[("station", "C", 0), ("elev_m", "N", 0)],
        rows=[
            ((36.8, -1.3), ("Nairobi", 1795)),
            ((39.2, -6.8), ("Dar es Salaam", 12)),
        ],
    )
    parts["prj"] = _WGS84_PRJ.encode()
    return _zip_archive(base_name, parts)


def _polygon_shapefile_zip(base_name: str = "parcels") -> bytes:
    parts = _shp_shx_dbf(
        shape_type=pyshp.POLYGON,
        fields=[("name", "C", 0), ("area_ha", "N", 2)],
        rows=[
            ([[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]], ("Field A", 12.5)),
            ([[[20, 20], [20, 30], [30, 30], [30, 20], [20, 20]]], ("Field B", 8.25)),
        ],
    )
    parts["prj"] = _WGS84_PRJ.encode()
    return _zip_archive(base_name, parts)


def _multipolygon_shapefile_zip(base_name: str = "islands") -> bytes:
    # A single feature with two disjoint rings — the ESRI Shapefile format
    # has no distinct "MultiPolygon" shape-type code (both single- and
    # multi-ring features use shape type 5, "Polygon"); GDAL/OGR still
    # correctly decodes this feature's actual WKB as a true MultiPolygon
    # (verified independently before this test suite was written).
    parts = _shp_shx_dbf(
        shape_type=pyshp.POLYGON,
        fields=[("region", "C", 0)],
        rows=[
            (
                [
                    [[0, 0], [0, 5], [5, 5], [5, 0], [0, 0]],
                    [[10, 10], [10, 15], [15, 15], [15, 10], [10, 10]],
                ],
                ("Two Islands",),
            )
        ],
    )
    parts["prj"] = _WGS84_PRJ.encode()
    return _zip_archive(base_name, parts)


async def _register_local_upload_source(session, tenant_id: TenantId) -> str:  # noqa: ANN001
    source = await RegisterDatasetSourceHandler(session).handle(
        RegisterDatasetSourceCommand(
            tenant_id=str(tenant_id),
            name="Shapefile Upload Source",
            provider="LOCAL_UPLOAD",
            description="",
            issued_by="analyst-1",
        )
    )
    return str(source.id)


async def _schedule_and_execute(
    session,  # noqa: ANN001
    tenant_id: TenantId,
    source_id: str,
    *,
    source_reference: str,
    zip_bytes: bytes,
    declared_crs: str = "EPSG:4326",
):
    job = await ScheduleAcquisitionJobHandler(session).handle(
        ScheduleAcquisitionJobCommand(
            tenant_id=str(tenant_id),
            provider="LOCAL_UPLOAD",
            source_reference=source_reference,
            format="SHAPEFILE",
            dataset_source_id=source_id,
            declared_crs=declared_crs,
            raw_content_base64=base64.b64encode(zip_bytes).decode(),
            issued_by="analyst-1",
        )
    )
    execute_handler = ExecuteAcquisitionJobHandler(
        session, _local_upload_registry(), _NullAoiReader()
    )
    return await execute_handler.handle(
        ExecuteAcquisitionJobCommand(
            tenant_id=str(tenant_id), acquisition_job_id=str(job.id), issued_by="analyst-1"
        )
    )


# --- Valid shapefiles: real geometry/attribute/CRS/bbox/feature-count ---


async def test_valid_point_shapefile_is_genuinely_parsed_and_catalogued(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    source_id = await _register_local_upload_source(db_session, tenant_id)

    completed = await _schedule_and_execute(
        db_session,
        tenant_id,
        source_id,
        source_reference="stations.zip",
        zip_bytes=_point_shapefile_zip(),
    )

    assert completed.status == AcquisitionJobStatus.COMPLETED, completed.error
    assert completed.shapefile_geometry_type == "Point"
    assert completed.shapefile_feature_count == 2
    assert completed.shapefile_crs == "EPSG:4326"
    assert completed.shapefile_bounding_box == pytest.approx((36.8, -6.8, 39.2, -1.3))
    assert completed.shapefile_attributes == {"station": "Nairobi", "elev_m": 1795}

    dataset_repo = SqlAlchemyDatasetRepository(db_session)
    dataset = await dataset_repo.get_by_id(completed.dataset_id)
    assert dataset is not None
    assert dataset.status == DatasetStatus.CATALOGUED
    assert dataset.metadata.crs == "EPSG:4326"
    assert "36.8" in dataset.metadata.spatial_coverage


async def test_valid_polygon_shapefile_is_genuinely_parsed_and_catalogued(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    source_id = await _register_local_upload_source(db_session, tenant_id)

    completed = await _schedule_and_execute(
        db_session,
        tenant_id,
        source_id,
        source_reference="parcels.zip",
        zip_bytes=_polygon_shapefile_zip(),
    )

    assert completed.status == AcquisitionJobStatus.COMPLETED, completed.error
    assert completed.shapefile_geometry_type == "Polygon"
    assert completed.shapefile_feature_count == 2
    assert completed.shapefile_bounding_box == pytest.approx((0.0, 0.0, 30.0, 30.0))
    assert completed.shapefile_attributes == {"name": "Field A", "area_ha": 12.5}


async def test_valid_multipolygon_shapefile_is_genuinely_detected_and_catalogued(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    source_id = await _register_local_upload_source(db_session, tenant_id)

    completed = await _schedule_and_execute(
        db_session,
        tenant_id,
        source_id,
        source_reference="islands.zip",
        zip_bytes=_multipolygon_shapefile_zip(),
    )

    assert completed.status == AcquisitionJobStatus.COMPLETED, completed.error
    # The whole point of reading actual per-feature WKB (not the
    # Shapefile-header shape-type code, which has no distinct
    # "MultiPolygon" value) — proves genuine parsing, not a header check.
    assert completed.shapefile_geometry_type == "MultiPolygon"
    assert completed.shapefile_feature_count == 1


# --- Incomplete archives: requirement #2's "reject incomplete datasets,
# name exactly which component is missing" ---


async def test_missing_dbf_is_rejected_with_clear_error(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    source_id = await _register_local_upload_source(db_session, tenant_id)
    parts = _shp_shx_dbf(
        shape_type=pyshp.POINT, fields=[("x", "C", 0)], rows=[((1, 2), ("a",))]
    )
    zip_bytes = _zip_archive(
        "incomplete", {"shp": parts["shp"], "shx": parts["shx"], "prj": _WGS84_PRJ.encode()}
    )

    failed = await _schedule_and_execute(
        db_session, tenant_id, source_id, source_reference="incomplete.zip", zip_bytes=zip_bytes
    )
    assert failed.status == AcquisitionJobStatus.FAILED
    assert "incomplete.dbf" in (failed.error or "")


async def test_missing_shx_is_rejected_with_clear_error(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    source_id = await _register_local_upload_source(db_session, tenant_id)
    parts = _shp_shx_dbf(
        shape_type=pyshp.POINT, fields=[("x", "C", 0)], rows=[((1, 2), ("a",))]
    )
    zip_bytes = _zip_archive(
        "incomplete", {"shp": parts["shp"], "dbf": parts["dbf"], "prj": _WGS84_PRJ.encode()}
    )

    failed = await _schedule_and_execute(
        db_session, tenant_id, source_id, source_reference="incomplete.zip", zip_bytes=zip_bytes
    )
    assert failed.status == AcquisitionJobStatus.FAILED
    assert "incomplete.shx" in (failed.error or "")


async def test_missing_prj_is_rejected_with_clear_error(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    source_id = await _register_local_upload_source(db_session, tenant_id)
    parts = _shp_shx_dbf(
        shape_type=pyshp.POINT, fields=[("x", "C", 0)], rows=[((1, 2), ("a",))]
    )
    zip_bytes = _zip_archive(
        "incomplete", {"shp": parts["shp"], "shx": parts["shx"], "dbf": parts["dbf"]}
    )

    failed = await _schedule_and_execute(
        db_session, tenant_id, source_id, source_reference="incomplete.zip", zip_bytes=zip_bytes
    )
    assert failed.status == AcquisitionJobStatus.FAILED
    assert "incomplete.prj" in (failed.error or "")


# --- Complete-but-broken archives: requirement #6's remaining reject list ---


async def test_corrupted_shapefile_is_rejected_with_clear_error(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    source_id = await _register_local_upload_source(db_session, tenant_id)
    parts = _shp_shx_dbf(
        shape_type=pyshp.POINT, fields=[("x", "C", 0)], rows=[((1, 2), ("a",))]
    )
    # All four components present (passes the completeness check) but the
    # .shp itself is severely truncated — genuinely unparseable, not just
    # a bad magic-byte header.
    zip_bytes = _zip_archive(
        "corrupt",
        {
            "shp": parts["shp"][:30],
            "shx": parts["shx"],
            "dbf": parts["dbf"],
            "prj": _WGS84_PRJ.encode(),
        },
    )

    failed = await _schedule_and_execute(
        db_session, tenant_id, source_id, source_reference="corrupt.zip", zip_bytes=zip_bytes
    )
    assert failed.status == AcquisitionJobStatus.FAILED
    assert failed.dataset_id is None


async def test_invalid_crs_is_rejected_with_clear_error(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    source_id = await _register_local_upload_source(db_session, tenant_id)
    parts = _shp_shx_dbf(
        shape_type=pyshp.POINT, fields=[("x", "C", 0)], rows=[((1, 2), ("a",))]
    )
    zip_bytes = _zip_archive(
        "badcrs",
        {
            "shp": parts["shp"],
            "shx": parts["shx"],
            "dbf": parts["dbf"],
            "prj": b"THIS IS NOT A VALID PROJECTION DEFINITION @#$%",
        },
    )

    failed = await _schedule_and_execute(
        db_session, tenant_id, source_id, source_reference="badcrs.zip", zip_bytes=zip_bytes
    )
    assert failed.status == AcquisitionJobStatus.FAILED
    assert "coordinate reference system" in (failed.error or "")


async def test_empty_shapefile_is_rejected_with_clear_error(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    source_id = await _register_local_upload_source(db_session, tenant_id)
    parts = _shp_shx_dbf(shape_type=pyshp.POINT, fields=[("x", "C", 0)], rows=[])
    zip_bytes = _zip_archive(
        "empty",
        {"shp": parts["shp"], "shx": parts["shx"], "dbf": parts["dbf"], "prj": _WGS84_PRJ.encode()},
    )

    failed = await _schedule_and_execute(
        db_session, tenant_id, source_id, source_reference="empty.zip", zip_bytes=zip_bytes
    )
    assert failed.status == AcquisitionJobStatus.FAILED
    assert "zero features" in (failed.error or "")


# --- Duplicate upload: must revise, never collide on an ambiguous
# version-1 duplicate ---


async def test_duplicate_upload_creates_a_new_dataset_version_not_a_collision(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    source_id = await _register_local_upload_source(db_session, tenant_id)

    first = await _schedule_and_execute(
        db_session,
        tenant_id,
        source_id,
        source_reference="parcels.zip",
        zip_bytes=_polygon_shapefile_zip(),
    )
    assert first.status == AcquisitionJobStatus.COMPLETED, first.error

    second = await _schedule_and_execute(
        db_session,
        tenant_id,
        source_id,
        source_reference="parcels.zip",
        zip_bytes=_polygon_shapefile_zip(),
    )
    assert second.status == AcquisitionJobStatus.COMPLETED, second.error
    assert second.dataset_id != first.dataset_id

    dataset_repo = SqlAlchemyDatasetRepository(db_session)
    first_dataset = await dataset_repo.get_by_id(first.dataset_id)
    second_dataset = await dataset_repo.get_by_id(second.dataset_id)
    assert first_dataset is not None
    assert second_dataset is not None
    assert first_dataset.status == DatasetStatus.SUPERSEDED
    assert second_dataset.status == DatasetStatus.CATALOGUED
    assert second_dataset.version == first_dataset.version + 1

    latest = await dataset_repo.get_latest(tenant_id, "parcels.zip")
    assert latest is not None
    assert latest.id == second_dataset.id


# --- Requirement #8/#9: Upload -> Extract -> Parse -> Validate -> Catalog
# -> Analysis, end to end, proving CompositionRootIndicatorInputProvider
# (Sprint A) genuinely reads a Shapefile-sourced dataset's real attribute
# values with zero stub/duplicate pipeline. Uses ``real_database`` (not
# ``db_session``): ``CompositionRootIndicatorInputProvider``/
# ``AnalysisStageExecutor`` each open their own sessions per call, the
# same reasoning Sprint A's own analysis-integration tests already
# established. ---


def _burn_severity_shapefile_zip(base_name: str = "burn-severity-plot") -> bytes:
    parts = _shp_shx_dbf(
        shape_type=pyshp.POINT,
        fields=_BURN_SEVERITY_FIELDS,
        rows=[((34.5, -2.3), tuple(_BURN_SEVERITY_VALUES.values()))],
    )
    parts["prj"] = _WGS84_PRJ.encode()
    return _zip_archive(base_name, parts)


async def test_upload_catalog_analysis_end_to_end_with_real_shapefile(
    real_database: Database,
) -> None:
    tenant_id = TenantId.new()

    # Upload -> Extract -> Parse -> Validate -> Catalog, via the real
    # pipeline (identical handlers/session pattern as every other test in
    # this file, just against a real_database session block instead of
    # the rollback-per-test db_session fixture, since the steps below
    # need a real, independently-connecting Database).
    async with real_database.session() as session:
        source_id = await _register_local_upload_source(session, tenant_id)
        job = await ScheduleAcquisitionJobHandler(session).handle(
            ScheduleAcquisitionJobCommand(
                tenant_id=str(tenant_id),
                provider="LOCAL_UPLOAD",
                # Sprint A's naming convention: CompositionRootIndicatorInputProvider
                # looks up a dataset named f"{hazard_type}:{stage_type}".
                source_reference="WILDFIRE:BURN_SEVERITY",
                format="SHAPEFILE",
                dataset_source_id=source_id,
                declared_crs="EPSG:4326",
                raw_content_base64=base64.b64encode(_burn_severity_shapefile_zip()).decode(),
                issued_by="analyst-1",
            )
        )
    async with real_database.session() as session:
        execute_handler = ExecuteAcquisitionJobHandler(
            session, _local_upload_registry(), _NullAoiReader()
        )
        completed = await execute_handler.handle(
            ExecuteAcquisitionJobCommand(
                tenant_id=str(tenant_id), acquisition_job_id=str(job.id), issued_by="analyst-1"
            )
        )
    assert completed.status == AcquisitionJobStatus.COMPLETED, completed.error
    assert completed.shapefile_geometry_type == "Point"
    assert completed.shapefile_attributes == _BURN_SEVERITY_VALUES

    # A real Assessment, so CompositionRootIndicatorInputProvider can
    # resolve this job's tenant from the assessment_id it's given.
    async with real_database.session() as session:
        assessment, _ = Assessment.create(
            tenant_id=tenant_id,
            name=f"Shapefile Analysis Integration {uuid.uuid4().hex[:8]}",
            hazard_type=AssessmentHazardType.WILDFIRE,
            created_by=UserId.new(),
        )
        assessment.mark_ready(changed_by="tester")
        await SqlAlchemyAssessmentRepository(session).save(assessment)
        await session.commit()

    # Analysis: the REAL IndicatorInputProvider (Sprint A), now also
    # reading a genuinely-parsed Shapefile's attribute table (Sprint B) —
    # no stub anywhere in this call path.
    registry = StrategyRegistry()
    registry.register(AnalysisHazardType.WILDFIRE, WRRASHazardStrategy())
    executor = AnalysisStageExecutor(
        real_database, registry, CompositionRootIndicatorInputProvider(real_database)
    )
    outcome = await executor.execute(
        AssessmentStageType.BURN_SEVERITY, assessment_id=str(assessment.id)
    )
    assert outcome.success is True, outcome.error

    async with real_database.session() as session:
        stage_result = await SqlAlchemyStageResultRepository(session).get_latest(
            tenant_id, str(assessment.id), AnalysisStageType.BURN_SEVERITY
        )
    assert stage_result is not None
    assert stage_result.status == StageResultStatus.COMPLETE
    # The persisted snapshot's raw inputs are exactly the values genuinely
    # read from the uploaded Shapefile's attribute table — proving the
    # imported geometries/attributes were truly used, not fabricated.
    for code, value in _BURN_SEVERITY_VALUES.items():
        assert stage_result.snapshot.inputs[code] == pytest.approx(value)
    assert stage_result.indicators is not None
