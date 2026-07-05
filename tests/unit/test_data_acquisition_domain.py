"""Domain-layer unit tests for the Data Acquisition context's aggregates
— pure logic, no I/O.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from georisk.contexts.data_acquisition.domain.entities import (
    AcquisitionJob,
    Dataset,
    DatasetSource,
    PredictorVariable,
    VariableSelection,
)
from georisk.contexts.data_acquisition.domain.errors import (
    IllegalAcquisitionJobTransitionError,
    InvalidAcquisitionJobError,
    InvalidVariableSelectionError,
)
from georisk.contexts.data_acquisition.domain.value_objects import (
    AcquisitionFormat,
    AcquisitionJobStatus,
    DataProvider,
    DatasetId,
    DatasetMetadata,
    DatasetReadinessTag,
    DatasetSourceId,
    DatasetStatus,
    DatasetType,
    PredictorVariableId,
    PreprocessingStep,
    ProcessingMethod,
    RemoteSensingSource,
    SpectralIndex,
    VariableCategory,
    VariableDataType,
    VariableRole,
    VariableSelectionStatus,
)
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.shared_kernel.types import DateRange

pytestmark = pytest.mark.unit


def _metadata(name: str = "CHIRPS Daily Rainfall") -> DatasetMetadata:
    return DatasetMetadata(
        name=name,
        dataset_type=DatasetType.RASTER,
        source="Satellite",
        provider=DataProvider.CHIRPS,
        acquisition_date=date(2026, 1, 1),
        spatial_resolution_m=5000.0,
        temporal_resolution=None,
        crs="EPSG:4326",
        spatial_coverage="Tanzania",
        temporal_coverage=DateRange(
            start=datetime(2020, 1, 1, tzinfo=UTC),
            end=datetime(2025, 12, 31, tzinfo=UTC),
        ),
        processing_method=ProcessingMethod.RAW,
    )


def test_register_dataset_source() -> None:
    source, event = DatasetSource.register(
        tenant_id=None,
        name="CHIRPS",
        provider=DataProvider.CHIRPS,
        description="Global rainfall estimates",
        created_by="admin-1",
    )
    assert source.is_active is True
    assert event.event_type == "data_acquisition.DatasetSourceRegistered"
    assert event.tenant_id is None


def test_catalog_dataset_produces_version_one_with_initial_provenance() -> None:
    source, _ = DatasetSource.register(
        tenant_id=None,
        name="CHIRPS",
        provider=DataProvider.CHIRPS,
        description="",
        created_by="admin-1",
    )
    dataset, event = Dataset.catalog(
        tenant_id=TenantId.new(),
        dataset_source_id=source.id,
        metadata=_metadata(),
        readiness=frozenset({DatasetReadinessTag.MLR_READY}),
        catalogued_by="analyst-1",
    )
    assert dataset.version == 1
    assert dataset.status == DatasetStatus.CATALOGUED
    assert len(dataset.provenance) == 1
    assert dataset.provenance[0].action == "CATALOGUED"
    assert DatasetReadinessTag.MLR_READY in dataset.readiness
    assert event.version == 1


def test_revise_dataset_appends_provenance_and_supersedes_previous() -> None:
    source, _ = DatasetSource.register(
        tenant_id=None,
        name="CHIRPS",
        provider=DataProvider.CHIRPS,
        description="",
        created_by="admin-1",
    )
    tenant_id = TenantId.new()
    first, _ = Dataset.catalog(
        tenant_id=tenant_id,
        dataset_source_id=source.id,
        metadata=_metadata(),
        readiness=frozenset(),
        catalogued_by="analyst-1",
    )
    revised_metadata = _metadata()
    second, event = Dataset.revise(
        previous=first,
        metadata=revised_metadata,
        readiness=frozenset({DatasetReadinessTag.CORRELATION_READY}),
        description="Reprocessed with cloud masking",
        catalogued_by="analyst-2",
    )
    first.mark_superseded()

    assert second.version == 2
    assert first.status == DatasetStatus.SUPERSEDED
    assert len(second.provenance) == 2
    assert second.provenance[-1].action == "REVISED"
    assert second.provenance[-1].source_reference == str(first.id)
    assert event.superseded_dataset_id == str(first.id)


def test_register_predictor_variable() -> None:
    variable, event = PredictorVariable.register(
        tenant_id=None,
        name="NDVI",
        code="ndvi",
        category=VariableCategory.VEGETATION_AND_FUEL,
        variable_role=VariableRole.INDEPENDENT,
        data_type=VariableDataType.CONTINUOUS,
        unit="index",
        value_min=-1.0,
        value_max=1.0,
        is_required_for_mlr=True,
        linked_dataset_id=None,
        created_by="admin-1",
    )
    assert variable.is_active is True
    assert variable.is_required_for_mlr is True
    assert event.category == "VEGETATION_AND_FUEL"


def test_variable_selection_requires_at_least_one_variable() -> None:
    with pytest.raises(InvalidVariableSelectionError):
        VariableSelection.create(
            tenant_id=TenantId.new(),
            name="Empty selection",
            hazard_type="WILDFIRE",
            selected_variable_ids=(),
            created_by="analyst-1",
        )


def test_variable_selection_confirm_transitions_status() -> None:
    selection, event = VariableSelection.create(
        tenant_id=TenantId.new(),
        name="WRRAS core variables",
        hazard_type="WILDFIRE",
        selected_variable_ids=(PredictorVariableId.new(), PredictorVariableId.new()),
        created_by="analyst-1",
    )
    assert selection.status == VariableSelectionStatus.DRAFT
    confirmed_event = selection.confirm()
    assert selection.status == VariableSelectionStatus.CONFIRMED
    assert confirmed_event.event_type == "data_acquisition.VariableSelectionConfirmed"
    assert event.variable_count == 2


def test_schedule_acquisition_job_rejects_non_acquisition_capable_provider() -> None:
    with pytest.raises(InvalidAcquisitionJobError):
        AcquisitionJob.schedule(
            tenant_id=TenantId.new(),
            provider=DataProvider.CHIRPS,
            source_reference="chirps-daily-2026",
            format=AcquisitionFormat.CSV,
            dataset_source_id=DatasetSourceId.new(),
            declared_crs="EPSG:4326",
            raw_content_base64=None,
            requested_by="analyst-1",
        )


def test_schedule_local_upload_requires_raw_content() -> None:
    with pytest.raises(InvalidAcquisitionJobError):
        AcquisitionJob.schedule(
            tenant_id=TenantId.new(),
            provider=DataProvider.LOCAL_UPLOAD,
            source_reference="my-upload.csv",
            format=AcquisitionFormat.CSV,
            dataset_source_id=DatasetSourceId.new(),
            declared_crs="EPSG:4326",
            raw_content_base64=None,
            requested_by="analyst-1",
        )


def _schedule_job(
    *, provider: DataProvider = DataProvider.USGS, raw_content_base64: str | None = None
) -> AcquisitionJob:
    job, _ = AcquisitionJob.schedule(
        tenant_id=TenantId.new(),
        provider=provider,
        source_reference="usgs-landsat-scene-42",
        format=AcquisitionFormat.GEOTIFF,
        dataset_source_id=DatasetSourceId.new(),
        declared_crs="EPSG:4326",
        raw_content_base64=raw_content_base64,
        requested_by="analyst-1",
    )
    return job


def test_schedule_acquisition_job_produces_scheduled_status_and_provenance() -> None:
    job = _schedule_job()
    assert job.status == AcquisitionJobStatus.SCHEDULED
    assert len(job.provenance) == 1
    assert job.provenance[0].action == "SCHEDULED"


def test_acquisition_job_full_lifecycle_to_completion() -> None:
    job = _schedule_job()
    started_event = job.start()
    assert job.status == AcquisitionJobStatus.RUNNING
    assert job.started_at is not None
    assert started_event.acquisition_job_id == str(job.id)

    dataset_id = DatasetId.new()
    completed_event = job.complete(dataset_id=dataset_id)
    assert job.status == AcquisitionJobStatus.COMPLETED
    assert job.dataset_id == dataset_id
    assert job.completed_at is not None
    assert completed_event.dataset_id == str(dataset_id)
    assert job.provenance[-1].action == "COMPLETED"


def test_acquisition_job_lifecycle_to_failure() -> None:
    job = _schedule_job()
    job.start()
    failed_event = job.fail(error="Fetch timed out")
    assert job.status == AcquisitionJobStatus.FAILED
    assert job.error == "Fetch timed out"
    assert failed_event.error == "Fetch timed out"
    assert job.provenance[-1].action == "FAILED"


def test_acquisition_job_cannot_start_twice() -> None:
    job = _schedule_job()
    job.start()
    with pytest.raises(IllegalAcquisitionJobTransitionError):
        job.start()


def test_acquisition_job_cannot_complete_before_starting() -> None:
    job = _schedule_job()
    with pytest.raises(IllegalAcquisitionJobTransitionError):
        job.complete(dataset_id=DatasetId.new())


def test_acquisition_job_cannot_fail_before_starting() -> None:
    job = _schedule_job()
    with pytest.raises(IllegalAcquisitionJobTransitionError):
        job.fail(error="too early")


# --- Sprint 14: Remote Sensing Integration ---


def test_schedule_gee_job_requires_remote_sensing_source() -> None:
    with pytest.raises(InvalidAcquisitionJobError):
        AcquisitionJob.schedule(
            tenant_id=TenantId.new(),
            provider=DataProvider.GOOGLE_EARTH_ENGINE,
            source_reference="ignored",
            format=AcquisitionFormat.GEOTIFF,
            dataset_source_id=DatasetSourceId.new(),
            declared_crs="EPSG:4326",
            raw_content_base64=None,
            requested_by="analyst-1",
            aoi_id="some-aoi-id",
        )


def test_schedule_gee_job_requires_aoi_id() -> None:
    with pytest.raises(InvalidAcquisitionJobError):
        AcquisitionJob.schedule(
            tenant_id=TenantId.new(),
            provider=DataProvider.GOOGLE_EARTH_ENGINE,
            source_reference="ignored",
            format=AcquisitionFormat.GEOTIFF,
            dataset_source_id=DatasetSourceId.new(),
            declared_crs="EPSG:4326",
            raw_content_base64=None,
            requested_by="analyst-1",
            remote_sensing_source=RemoteSensingSource.SENTINEL_2,
        )


def test_schedule_gee_job_with_valid_remote_sensing_fields() -> None:
    job, event = AcquisitionJob.schedule(
        tenant_id=TenantId.new(),
        provider=DataProvider.GOOGLE_EARTH_ENGINE,
        source_reference="sentinel-2-composite",
        format=AcquisitionFormat.GEOTIFF,
        dataset_source_id=DatasetSourceId.new(),
        declared_crs="EPSG:4326",
        raw_content_base64=None,
        requested_by="analyst-1",
        remote_sensing_source=RemoteSensingSource.SENTINEL_2,
        aoi_id="aoi-123",
        requested_preprocessing=(
            PreprocessingStep.CLOUD_MASKING,
            PreprocessingStep.RADIOMETRIC_CORRECTION,
        ),
        requested_indices=(SpectralIndex.NDVI, SpectralIndex.EVI),
    )
    assert job.remote_sensing_source == RemoteSensingSource.SENTINEL_2
    assert job.aoi_id == "aoi-123"
    assert job.requested_preprocessing == (
        PreprocessingStep.CLOUD_MASKING,
        PreprocessingStep.RADIOMETRIC_CORRECTION,
    )
    assert job.requested_indices == (SpectralIndex.NDVI, SpectralIndex.EVI)
    assert job.applied_preprocessing == ()
    assert job.extracted_features is None
    assert event.provider == "GOOGLE_EARTH_ENGINE"


def test_complete_records_applied_preprocessing_and_extracted_features() -> None:
    job = _schedule_job(provider=DataProvider.LOCAL_UPLOAD, raw_content_base64="ignored")
    job.start()
    completed_event = job.complete(
        dataset_id=DatasetId.new(),
        applied_preprocessing=(PreprocessingStep.REPROJECTION,),
        extracted_features={"NDVI": 0.42},
        skipped_features={"LST": "no thermal band"},
    )
    assert job.applied_preprocessing == (PreprocessingStep.REPROJECTION,)
    assert job.extracted_features == {"NDVI": 0.42}
    assert job.skipped_features == {"LST": "no thermal band"}
    assert "NDVI" in job.provenance[-1].description
    assert completed_event.dataset_id == str(job.dataset_id)
