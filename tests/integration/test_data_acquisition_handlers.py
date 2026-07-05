"""Handler-level integration tests against a real Postgres instance for
the Data Acquisition context's command pipeline.
"""

from __future__ import annotations

import base64
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from georisk.contexts.data_acquisition.application.commands import (
    CatalogDatasetCommand,
    ConfirmVariableSelectionCommand,
    CreateVariableSelectionCommand,
    ExecuteAcquisitionJobCommand,
    RegisterDatasetSourceCommand,
    RegisterPredictorVariableCommand,
    ReviseDatasetCommand,
    ScheduleAcquisitionJobCommand,
)
from georisk.contexts.data_acquisition.application.handlers import (
    CatalogDatasetHandler,
    ConfirmVariableSelectionHandler,
    CreateVariableSelectionHandler,
    ExecuteAcquisitionJobHandler,
    RegisterDatasetSourceHandler,
    RegisterPredictorVariableHandler,
    ReviseDatasetHandler,
    ScheduleAcquisitionJobHandler,
)
from georisk.contexts.data_acquisition.application.ports import (
    AoiGeometryInfo,
    FetchResult,
    LocalUploadProvider,
    ProviderRegistry,
)
from georisk.contexts.data_acquisition.domain.errors import DatasetSourceNotFoundError
from georisk.contexts.data_acquisition.domain.value_objects import (
    AcquisitionJobStatus,
    DataProvider,
    DatasetStatus,
    PreprocessingStep,
    RemoteSensingSource,
    VariableSelectionStatus,
)
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.db.outbox_models import OutboxEventModel

pytestmark = pytest.mark.integration


def _local_upload_registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(DataProvider.LOCAL_UPLOAD, LocalUploadProvider())
    return registry


class _NullAoiReader:
    """Never actually called by tests whose job has no ``aoi_id`` — the
    handler only invokes ``AoiReader`` when ``job.aoi_id is not None``."""

    async def get_aoi_geometry(self, *, tenant_id, aoi_id):  # noqa: ANN001
        raise AssertionError("AoiReader should not be called for a job with no aoi_id")


class _FakeAoiReader:
    def __init__(self, geometries: dict[str, dict]) -> None:
        self._geometries = geometries

    async def get_aoi_geometry(self, *, tenant_id, aoi_id):  # noqa: ANN001
        geometry = self._geometries.get(aoi_id)
        if geometry is None:
            return None
        return AoiGeometryInfo(aoi_id=aoi_id, geometry=geometry)


class _FakeGeeProvider:
    """Simulates ``GoogleEarthEngineProvider`` without touching real
    ``ee``/network — real GEE connectivity is proven separately (skipped
    when unconfigured) by ``tests/integration/test_gee_connectivity.py``.
    """

    def __init__(self, result: FetchResult) -> None:
        self._result = result

    async def fetch(self, *, source_reference, raw_content=None, spec=None):  # noqa: ANN001
        return self._result


async def test_register_dataset_source_then_catalog_and_revise_dataset(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()

    source_handler = RegisterDatasetSourceHandler(db_session)
    source = await source_handler.handle(
        RegisterDatasetSourceCommand(
            tenant_id=str(tenant_id),
            name="CHIRPS",
            provider="CHIRPS",
            description="Rainfall estimates",
            issued_by="admin-1",
        )
    )

    catalog_handler = CatalogDatasetHandler(db_session)
    dataset = await catalog_handler.handle(
        CatalogDatasetCommand(
            tenant_id=str(tenant_id),
            dataset_source_id=str(source.id),
            name="Rainfall 2020-2025",
            dataset_type="RASTER",
            source="Satellite",
            provider="CHIRPS",
            acquisition_date=date(2026, 1, 1),
            crs="EPSG:4326",
            spatial_coverage="Tanzania",
            temporal_coverage_start="2020-01-01T00:00:00+00:00",
            temporal_coverage_end="2025-12-31T00:00:00+00:00",
            processing_method="RAW",
            spatial_resolution_m=5000.0,
            is_mlr_ready=True,
            issued_by="analyst-1",
        )
    )
    assert dataset.version == 1
    assert dataset.status == DatasetStatus.CATALOGUED

    revise_handler = ReviseDatasetHandler(db_session)
    revised = await revise_handler.handle(
        ReviseDatasetCommand(
            tenant_id=str(tenant_id),
            dataset_name="Rainfall 2020-2025",
            dataset_type="RASTER",
            source="Satellite",
            provider="CHIRPS",
            acquisition_date=date(2026, 2, 1),
            crs="EPSG:4326",
            spatial_coverage="Tanzania",
            temporal_coverage_start="2020-01-01T00:00:00+00:00",
            temporal_coverage_end="2026-01-31T00:00:00+00:00",
            processing_method="CLOUD_MASKED",
            description="Reprocessed with cloud masking, extended coverage",
            spatial_resolution_m=5000.0,
            is_mlr_ready=True,
            issued_by="analyst-2",
        )
    )
    assert revised.version == 2
    assert revised.metadata.processing_method.value == "CLOUD_MASKED"
    assert len(revised.provenance) == 2

    outbox = await db_session.execute(
        select(OutboxEventModel).where(OutboxEventModel.aggregate_type == "Dataset")
    )
    event_types = {e.event_type for e in outbox.scalars().all()}
    assert event_types == {"data_acquisition.DatasetCatalogued", "data_acquisition.DatasetRevised"}


# --- Security regression: cross-tenant DatasetSource isolation
# (SECURITY_REVIEW.md §3 High finding, fixed via
# _assert_dataset_source_visible_to_tenant) ---


async def test_catalog_dataset_rejects_cross_tenant_private_dataset_source(db_session) -> None:  # noqa: ANN001
    tenant_a = TenantId.new()
    tenant_b = TenantId.new()

    source = await RegisterDatasetSourceHandler(db_session).handle(
        RegisterDatasetSourceCommand(
            tenant_id=str(tenant_a),
            name="Tenant A's private source",
            provider="USER_UPLOAD",
            description="",
            issued_by="tenant-a-admin",
        )
    )

    with pytest.raises(DatasetSourceNotFoundError):
        await CatalogDatasetHandler(db_session).handle(
            CatalogDatasetCommand(
                tenant_id=str(tenant_b),
                dataset_source_id=str(source.id),
                name="Attempted cross-tenant catalog",
                dataset_type="RASTER",
                source="attacker",
                provider="USER_UPLOAD",
                acquisition_date=date(2026, 1, 1),
                crs="EPSG:4326",
                spatial_coverage="N/A",
                temporal_coverage_start="2026-01-01T00:00:00+00:00",
                temporal_coverage_end="2026-01-01T00:00:00+00:00",
                processing_method="RAW",
                issued_by="tenant-b-attacker",
            )
        )


async def test_catalog_dataset_allows_global_dataset_source_from_any_tenant(db_session) -> None:  # noqa: ANN001
    tenant_c = TenantId.new()

    global_source = await RegisterDatasetSourceHandler(db_session).handle(
        RegisterDatasetSourceCommand(
            tenant_id=None,
            name="Global CHIRPS registration",
            provider="CHIRPS",
            description="Public, shared across all tenants",
            issued_by="platform-admin",
        )
    )

    dataset = await CatalogDatasetHandler(db_session).handle(
        CatalogDatasetCommand(
            tenant_id=str(tenant_c),
            dataset_source_id=str(global_source.id),
            name="Tenant C using the global source",
            dataset_type="RASTER",
            source="global",
            provider="CHIRPS",
            acquisition_date=date(2026, 1, 1),
            crs="EPSG:4326",
            spatial_coverage="N/A",
            temporal_coverage_start="2026-01-01T00:00:00+00:00",
            temporal_coverage_end="2026-01-01T00:00:00+00:00",
            processing_method="RAW",
            issued_by="tenant-c-admin",
        )
    )
    assert dataset.dataset_source_id == global_source.id


async def test_schedule_acquisition_job_rejects_cross_tenant_private_dataset_source(
    db_session,  # noqa: ANN001
) -> None:
    tenant_a = TenantId.new()
    tenant_b = TenantId.new()

    source = await RegisterDatasetSourceHandler(db_session).handle(
        RegisterDatasetSourceCommand(
            tenant_id=str(tenant_a),
            name="Tenant A's private local upload source",
            provider="LOCAL_UPLOAD",
            description="",
            issued_by="tenant-a-admin",
        )
    )

    with pytest.raises(DatasetSourceNotFoundError):
        await ScheduleAcquisitionJobHandler(db_session).handle(
            ScheduleAcquisitionJobCommand(
                tenant_id=str(tenant_b),
                provider="LOCAL_UPLOAD",
                source_reference="attacker-scheduled-job",
                format="CSV",
                dataset_source_id=str(source.id),
                declared_crs="EPSG:4326",
                raw_content_base64="ZmFrZQ==",
                issued_by="tenant-b-attacker",
            )
        )


async def test_schedule_acquisition_job_allows_same_tenant_private_dataset_source(
    db_session,  # noqa: ANN001
) -> None:
    tenant_a = TenantId.new()

    source = await RegisterDatasetSourceHandler(db_session).handle(
        RegisterDatasetSourceCommand(
            tenant_id=str(tenant_a),
            name="Tenant A's own local upload source",
            provider="LOCAL_UPLOAD",
            description="",
            issued_by="tenant-a-admin",
        )
    )

    job = await ScheduleAcquisitionJobHandler(db_session).handle(
        ScheduleAcquisitionJobCommand(
            tenant_id=str(tenant_a),
            provider="LOCAL_UPLOAD",
            source_reference="own-job",
            format="CSV",
            dataset_source_id=str(source.id),
            declared_crs="EPSG:4326",
            raw_content_base64="ZmFrZQ==",
            issued_by="tenant-a-admin",
        )
    )
    assert job.dataset_source_id == source.id


async def test_register_predictor_variable_and_create_confirm_selection(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    variable_handler = RegisterPredictorVariableHandler(db_session)

    ndvi = await variable_handler.handle(
        RegisterPredictorVariableCommand(
            tenant_id=str(tenant_id),
            name="NDVI",
            code="ndvi",
            category="VEGETATION_AND_FUEL",
            variable_role="INDEPENDENT",
            data_type="CONTINUOUS",
            unit="index",
            is_required_for_mlr=True,
            issued_by="admin-1",
        )
    )
    wind = await variable_handler.handle(
        RegisterPredictorVariableCommand(
            tenant_id=str(tenant_id),
            name="Wind Speed",
            code="wind_speed",
            category="METEOROLOGICAL",
            variable_role="INDEPENDENT",
            data_type="CONTINUOUS",
            unit="m/s",
            is_required_for_mlr=True,
            issued_by="admin-1",
        )
    )

    selection_handler = CreateVariableSelectionHandler(db_session)
    selection = await selection_handler.handle(
        CreateVariableSelectionCommand(
            tenant_id=str(tenant_id),
            name="WRRAS core variables",
            hazard_type="WILDFIRE",
            selected_variable_ids=(str(ndvi.id), str(wind.id)),
            issued_by="analyst-1",
        )
    )
    assert selection.status == VariableSelectionStatus.DRAFT

    confirm_handler = ConfirmVariableSelectionHandler(db_session)
    confirmed = await confirm_handler.handle(
        ConfirmVariableSelectionCommand(
            tenant_id=str(tenant_id), variable_selection_id=str(selection.id)
        )
    )
    assert confirmed.status == VariableSelectionStatus.CONFIRMED

    outbox = await db_session.execute(
        select(OutboxEventModel).where(OutboxEventModel.aggregate_type == "VariableSelection")
    )
    event_types = {e.event_type for e in outbox.scalars().all()}
    assert event_types == {
        "data_acquisition.VariableSelectionCreated",
        "data_acquisition.VariableSelectionConfirmed",
    }


async def test_schedule_and_execute_local_upload_acquisition_job_catalogs_dataset(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()

    source_handler = RegisterDatasetSourceHandler(db_session)
    source = await source_handler.handle(
        RegisterDatasetSourceCommand(
            tenant_id=str(tenant_id),
            name="Local Upload Source",
            provider="LOCAL_UPLOAD",
            description="Manually uploaded files",
            issued_by="admin-1",
        )
    )

    csv_content = b"station,rainfall_mm\nA,12.5\nB,8.3\n"
    schedule_handler = ScheduleAcquisitionJobHandler(db_session)
    job = await schedule_handler.handle(
        ScheduleAcquisitionJobCommand(
            tenant_id=str(tenant_id),
            provider="LOCAL_UPLOAD",
            source_reference="station-rainfall.csv",
            format="CSV",
            dataset_source_id=str(source.id),
            declared_crs="EPSG:4326",
            raw_content_base64=base64.b64encode(csv_content).decode(),
            issued_by="analyst-1",
        )
    )
    assert job.status == AcquisitionJobStatus.SCHEDULED

    execute_handler = ExecuteAcquisitionJobHandler(
        db_session, _local_upload_registry(), _NullAoiReader()
    )
    completed_job = await execute_handler.handle(
        ExecuteAcquisitionJobCommand(
            tenant_id=str(tenant_id), acquisition_job_id=str(job.id), issued_by="analyst-1"
        )
    )
    assert completed_job.status == AcquisitionJobStatus.COMPLETED
    assert completed_job.dataset_id is not None

    dataset_outbox = await db_session.execute(
        select(OutboxEventModel).where(
            OutboxEventModel.aggregate_type == "Dataset",
            OutboxEventModel.aggregate_id == str(completed_job.dataset_id),
        )
    )
    assert {e.event_type for e in dataset_outbox.scalars().all()} == {
        "data_acquisition.DatasetCatalogued"
    }

    job_outbox = await db_session.execute(
        select(OutboxEventModel).where(
            OutboxEventModel.aggregate_type == "AcquisitionJob",
            OutboxEventModel.aggregate_id == str(job.id),
        )
    )
    job_event_types = {e.event_type for e in job_outbox.scalars().all()}
    assert job_event_types == {
        "data_acquisition.AcquisitionJobScheduled",
        "data_acquisition.AcquisitionJobStarted",
        "data_acquisition.AcquisitionJobCompleted",
    }


async def test_execute_acquisition_job_fails_on_invalid_content(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()

    source_handler = RegisterDatasetSourceHandler(db_session)
    source = await source_handler.handle(
        RegisterDatasetSourceCommand(
            tenant_id=str(tenant_id),
            name="Local Upload Source",
            provider="LOCAL_UPLOAD",
            description="",
            issued_by="admin-1",
        )
    )

    schedule_handler = ScheduleAcquisitionJobHandler(db_session)
    job = await schedule_handler.handle(
        ScheduleAcquisitionJobCommand(
            tenant_id=str(tenant_id),
            provider="LOCAL_UPLOAD",
            source_reference="not-a-real-tiff.tif",
            format="GEOTIFF",
            dataset_source_id=str(source.id),
            declared_crs="EPSG:4326",
            raw_content_base64=base64.b64encode(b"this is not a tiff").decode(),
            issued_by="analyst-1",
        )
    )

    execute_handler = ExecuteAcquisitionJobHandler(
        db_session, _local_upload_registry(), _NullAoiReader()
    )
    failed_job = await execute_handler.handle(
        ExecuteAcquisitionJobCommand(
            tenant_id=str(tenant_id), acquisition_job_id=str(job.id), issued_by="analyst-1"
        )
    )
    assert failed_job.status == AcquisitionJobStatus.FAILED
    assert failed_job.error is not None
    assert failed_job.dataset_id is None

    job_outbox = await db_session.execute(
        select(OutboxEventModel).where(
            OutboxEventModel.aggregate_type == "AcquisitionJob",
            OutboxEventModel.aggregate_id == str(job.id),
        )
    )
    job_event_types = {e.event_type for e in job_outbox.scalars().all()}
    assert job_event_types == {
        "data_acquisition.AcquisitionJobScheduled",
        "data_acquisition.AcquisitionJobStarted",
        "data_acquisition.AcquisitionJobFailed",
    }


async def test_execute_acquisition_job_fails_when_no_provider_registered(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()

    source_handler = RegisterDatasetSourceHandler(db_session)
    source = await source_handler.handle(
        RegisterDatasetSourceCommand(
            tenant_id=str(tenant_id),
            name="USGS Source",
            provider="USGS",
            description="",
            issued_by="admin-1",
        )
    )

    schedule_handler = ScheduleAcquisitionJobHandler(db_session)
    job = await schedule_handler.handle(
        ScheduleAcquisitionJobCommand(
            tenant_id=str(tenant_id),
            provider="USGS",
            source_reference="scene-1",
            format="GEOTIFF",
            dataset_source_id=str(source.id),
            declared_crs="EPSG:4326",
            issued_by="analyst-1",
        )
    )

    empty_registry = ProviderRegistry()
    execute_handler = ExecuteAcquisitionJobHandler(db_session, empty_registry, _NullAoiReader())
    failed_job = await execute_handler.handle(
        ExecuteAcquisitionJobCommand(
            tenant_id=str(tenant_id), acquisition_job_id=str(job.id), issued_by="analyst-1"
        )
    )
    assert failed_job.status == AcquisitionJobStatus.FAILED
    assert "No AcquisitionProvider registered" in (failed_job.error or "")


# --- Sprint 14: Remote Sensing Integration ---

_FAKE_TIFF_CONTENT = b"II*\x00" + b"\x00" * 20
_FAKE_AOI_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]],
}
# aoi_id is a soft cross-context reference stored as a UUID column
# (same convention as Geospatial's own assessment_id), so test fixtures
# use real UUID strings rather than arbitrary placeholder text.
_FAKE_AOI_ID = str(uuid.uuid4())
_MISSING_AOI_ID = str(uuid.uuid4())


async def test_schedule_and_execute_gee_job_with_aoi_computes_features(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()

    source_handler = RegisterDatasetSourceHandler(db_session)
    source = await source_handler.handle(
        RegisterDatasetSourceCommand(
            tenant_id=str(tenant_id),
            name="GEE Sentinel-2 Source",
            provider="GOOGLE_EARTH_ENGINE",
            description="",
            issued_by="admin-1",
        )
    )

    schedule_handler = ScheduleAcquisitionJobHandler(db_session)
    job = await schedule_handler.handle(
        ScheduleAcquisitionJobCommand(
            tenant_id=str(tenant_id),
            provider="GOOGLE_EARTH_ENGINE",
            source_reference="sentinel-2-composite",
            format="GEOTIFF",
            dataset_source_id=str(source.id),
            declared_crs="EPSG:4326",
            remote_sensing_source="SENTINEL_2",
            aoi_id=_FAKE_AOI_ID,
            requested_preprocessing=("RADIOMETRIC_CORRECTION", "AOI_CLIPPING"),
            requested_indices=("NDVI", "LST"),
            issued_by="analyst-1",
        )
    )
    assert job.remote_sensing_source == RemoteSensingSource.SENTINEL_2

    registry = ProviderRegistry()
    registry.register(
        DataProvider.GOOGLE_EARTH_ENGINE,
        _FakeGeeProvider(
            FetchResult(
                success=True,
                content=_FAKE_TIFF_CONTENT,
                error=None,
                applied_preprocessing=(
                    PreprocessingStep.RADIOMETRIC_CORRECTION,
                    PreprocessingStep.AOI_CLIPPING,
                ),
                band_statistics={"B8": 0.5, "B4": 0.1},
            )
        ),
    )
    aoi_reader = _FakeAoiReader({_FAKE_AOI_ID: _FAKE_AOI_GEOMETRY})

    execute_handler = ExecuteAcquisitionJobHandler(db_session, registry, aoi_reader)
    completed_job = await execute_handler.handle(
        ExecuteAcquisitionJobCommand(
            tenant_id=str(tenant_id), acquisition_job_id=str(job.id), issued_by="analyst-1"
        )
    )

    assert completed_job.status == AcquisitionJobStatus.COMPLETED
    assert completed_job.applied_preprocessing == (
        PreprocessingStep.RADIOMETRIC_CORRECTION,
        PreprocessingStep.AOI_CLIPPING,
    )
    assert completed_job.extracted_features is not None
    assert completed_job.extracted_features["NDVI"] == pytest.approx((0.5 - 0.1) / (0.5 + 0.1))
    assert completed_job.skipped_features is not None
    assert "LST" in completed_job.skipped_features  # Sentinel-2 has no thermal band


async def test_execute_gee_job_fails_when_aoi_not_found(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()

    source_handler = RegisterDatasetSourceHandler(db_session)
    source = await source_handler.handle(
        RegisterDatasetSourceCommand(
            tenant_id=str(tenant_id),
            name="GEE Source",
            provider="GOOGLE_EARTH_ENGINE",
            description="",
            issued_by="admin-1",
        )
    )

    schedule_handler = ScheduleAcquisitionJobHandler(db_session)
    job = await schedule_handler.handle(
        ScheduleAcquisitionJobCommand(
            tenant_id=str(tenant_id),
            provider="GOOGLE_EARTH_ENGINE",
            source_reference="sentinel-2-composite",
            format="GEOTIFF",
            dataset_source_id=str(source.id),
            declared_crs="EPSG:4326",
            remote_sensing_source="SENTINEL_2",
            aoi_id=_MISSING_AOI_ID,
            issued_by="analyst-1",
        )
    )

    registry = ProviderRegistry()
    registry.register(DataProvider.GOOGLE_EARTH_ENGINE, _FakeGeeProvider(FetchResult(
        success=True, content=_FAKE_TIFF_CONTENT, error=None
    )))
    aoi_reader = _FakeAoiReader({})  # empty — _MISSING_AOI_ID resolves to None

    execute_handler = ExecuteAcquisitionJobHandler(db_session, registry, aoi_reader)
    failed_job = await execute_handler.handle(
        ExecuteAcquisitionJobCommand(
            tenant_id=str(tenant_id), acquisition_job_id=str(job.id), issued_by="analyst-1"
        )
    )
    assert failed_job.status == AcquisitionJobStatus.FAILED
    assert f"AreaOfInterest {_MISSING_AOI_ID} not found" in (failed_job.error or "")


async def test_execute_gee_job_computes_dnbr_with_comparison_window(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()

    source_handler = RegisterDatasetSourceHandler(db_session)
    source = await source_handler.handle(
        RegisterDatasetSourceCommand(
            tenant_id=str(tenant_id),
            name="GEE Landsat Source",
            provider="GOOGLE_EARTH_ENGINE",
            description="",
            issued_by="admin-1",
        )
    )

    schedule_handler = ScheduleAcquisitionJobHandler(db_session)
    job = await schedule_handler.handle(
        ScheduleAcquisitionJobCommand(
            tenant_id=str(tenant_id),
            provider="GOOGLE_EARTH_ENGINE",
            source_reference="landsat-burn-scar",
            format="GEOTIFF",
            dataset_source_id=str(source.id),
            declared_crs="EPSG:4326",
            remote_sensing_source="LANDSAT",
            aoi_id=_FAKE_AOI_ID,
            comparison_temporal_start="2025-01-01T00:00:00",
            comparison_temporal_end="2025-01-31T00:00:00",
            requested_indices=("DNBR",),
            issued_by="analyst-1",
        )
    )

    registry = ProviderRegistry()
    registry.register(
        DataProvider.GOOGLE_EARTH_ENGINE,
        _FakeGeeProvider(
            FetchResult(
                success=True,
                content=_FAKE_TIFF_CONTENT,
                error=None,
                band_statistics={"SR_B5": 0.5, "SR_B7": 0.1},
                comparison_band_statistics={"SR_B5": 0.2, "SR_B7": 0.3},
            )
        ),
    )
    aoi_reader = _FakeAoiReader({_FAKE_AOI_ID: _FAKE_AOI_GEOMETRY})

    execute_handler = ExecuteAcquisitionJobHandler(db_session, registry, aoi_reader)
    completed_job = await execute_handler.handle(
        ExecuteAcquisitionJobCommand(
            tenant_id=str(tenant_id), acquisition_job_id=str(job.id), issued_by="analyst-1"
        )
    )
    assert completed_job.status == AcquisitionJobStatus.COMPLETED
    assert completed_job.extracted_features is not None
    pre_nbr = (0.5 - 0.1) / (0.5 + 0.1)
    post_nbr = (0.2 - 0.3) / (0.2 + 0.3)
    assert completed_job.extracted_features["DNBR"] == pytest.approx(pre_nbr - post_nbr)
