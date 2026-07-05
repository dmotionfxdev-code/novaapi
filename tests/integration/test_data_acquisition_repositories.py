"""Repository-level integration tests against a real Postgres instance —
confirms the Data Acquisition context's domain<->ORM mapping round-trips
correctly, including ``Dataset``'s version/provenance/readiness fields.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest

from georisk.contexts.data_acquisition.domain.entities import (
    AcquisitionJob,
    Dataset,
    DatasetSource,
    PredictorVariable,
)
from georisk.contexts.data_acquisition.domain.value_objects import (
    AcquisitionFormat,
    AcquisitionJobStatus,
    DataProvider,
    DatasetId,
    DatasetMetadata,
    DatasetReadinessTag,
    DatasetType,
    PreprocessingStep,
    ProcessingMethod,
    RemoteSensingSource,
    SpectralIndex,
    VariableCategory,
    VariableDataType,
    VariableRole,
)
from georisk.contexts.data_acquisition.infrastructure.repositories import (
    SqlAlchemyAcquisitionJobRepository,
    SqlAlchemyDatasetRepository,
    SqlAlchemyDatasetSourceRepository,
    SqlAlchemyPredictorVariableRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.shared_kernel.types import DateRange

pytestmark = pytest.mark.integration


def _metadata(name: str) -> DatasetMetadata:
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


async def test_dataset_source_save_and_list_available(db_session) -> None:  # noqa: ANN001
    repo = SqlAlchemyDatasetSourceRepository(db_session)
    tenant_id = TenantId.new()

    global_source, _ = DatasetSource.register(
        tenant_id=None,
        name="Global CHIRPS",
        provider=DataProvider.CHIRPS,
        description="",
        created_by="admin-1",
    )
    private_source, _ = DatasetSource.register(
        tenant_id=tenant_id,
        name="Tenant Upload",
        provider=DataProvider.USER_UPLOAD,
        description="",
        created_by="admin-1",
    )
    other_tenant_source, _ = DatasetSource.register(
        tenant_id=TenantId.new(),
        name="Someone Else's Upload",
        provider=DataProvider.USER_UPLOAD,
        description="",
        created_by="admin-1",
    )
    await repo.save(global_source)
    await repo.save(private_source)
    await repo.save(other_tenant_source)
    await db_session.flush()

    available = await repo.list_available(tenant_id)
    names = {s.name for s in available}
    assert names == {"Global CHIRPS", "Tenant Upload"}


async def test_dataset_save_get_and_version_history(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    source_repo = SqlAlchemyDatasetSourceRepository(db_session)
    dataset_repo = SqlAlchemyDatasetRepository(db_session)

    source, _ = DatasetSource.register(
        tenant_id=None,
        name="CHIRPS",
        provider=DataProvider.CHIRPS,
        description="",
        created_by="admin-1",
    )
    await source_repo.save(source)
    await db_session.flush()

    first, _ = Dataset.catalog(
        tenant_id=tenant_id,
        dataset_source_id=source.id,
        metadata=_metadata("Rainfall v1"),
        readiness=frozenset({DatasetReadinessTag.MLR_READY}),
        catalogued_by="analyst-1",
    )
    await dataset_repo.save(first)
    await db_session.flush()

    fetched = await dataset_repo.get_by_id(first.id)
    assert fetched is not None
    assert fetched.metadata.name == "Rainfall v1"
    assert DatasetReadinessTag.MLR_READY in fetched.readiness
    assert len(fetched.provenance) == 1

    second, _ = Dataset.revise(
        previous=first,
        metadata=_metadata("Rainfall v1"),
        readiness=frozenset({DatasetReadinessTag.MLR_READY, DatasetReadinessTag.CORRELATION_READY}),
        description="Reprocessed",
        catalogued_by="analyst-2",
    )
    first.mark_superseded()
    await dataset_repo.save(first)
    await dataset_repo.save(second)
    await db_session.flush()

    latest = await dataset_repo.get_latest(tenant_id, "Rainfall v1")
    assert latest is not None
    assert latest.version == 2

    versions = await dataset_repo.list_versions(tenant_id, "Rainfall v1")
    assert [v.version for v in versions] == [1, 2]
    assert len(versions[1].provenance) == 2

    catalog = await dataset_repo.list_catalog(tenant_id)
    assert len(catalog) == 1
    assert catalog[0].version == 2

    mlr_ready = await dataset_repo.list_catalog(
        tenant_id, readiness=DatasetReadinessTag.MLR_READY
    )
    assert len(mlr_ready) == 1


async def test_predictor_variable_save_and_filter_by_category(db_session) -> None:  # noqa: ANN001
    repo = SqlAlchemyPredictorVariableRepository(db_session)
    tenant_id = TenantId.new()

    ndvi, _ = PredictorVariable.register(
        tenant_id=tenant_id,
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
    wind, _ = PredictorVariable.register(
        tenant_id=tenant_id,
        name="Wind Speed",
        code="wind_speed",
        category=VariableCategory.METEOROLOGICAL,
        variable_role=VariableRole.INDEPENDENT,
        data_type=VariableDataType.CONTINUOUS,
        unit="m/s",
        value_min=0.0,
        value_max=None,
        is_required_for_mlr=True,
        linked_dataset_id=None,
        created_by="admin-1",
    )
    await repo.save(ndvi)
    await repo.save(wind)
    await db_session.flush()

    all_variables = await repo.list_available(tenant_id)
    assert {v.name for v in all_variables} == {"NDVI", "Wind Speed"}

    vegetation_only = await repo.list_available(
        tenant_id, category=VariableCategory.VEGETATION_AND_FUEL.value
    )
    assert [v.name for v in vegetation_only] == ["NDVI"]


async def test_acquisition_job_save_get_and_lifecycle_round_trip(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    source_repo = SqlAlchemyDatasetSourceRepository(db_session)
    job_repo = SqlAlchemyAcquisitionJobRepository(db_session)

    source, _ = DatasetSource.register(
        tenant_id=None,
        name="USGS Landsat",
        provider=DataProvider.USGS,
        description="",
        created_by="admin-1",
    )
    await source_repo.save(source)
    await db_session.flush()

    job, _ = AcquisitionJob.schedule(
        tenant_id=tenant_id,
        provider=DataProvider.USGS,
        source_reference="landsat-scene-42",
        format=AcquisitionFormat.GEOTIFF,
        dataset_source_id=source.id,
        declared_crs="EPSG:4326",
        raw_content_base64=None,
        requested_by="analyst-1",
    )
    await job_repo.save(job)
    await db_session.flush()

    fetched = await job_repo.get_by_id(job.id)
    assert fetched is not None
    assert fetched.status == AcquisitionJobStatus.SCHEDULED
    assert fetched.provider == DataProvider.USGS
    assert len(fetched.provenance) == 1

    fetched.start()
    await job_repo.save(fetched)
    await db_session.flush()

    dataset_id = DatasetId.new()
    fetched.complete(dataset_id=dataset_id)
    await job_repo.save(fetched)
    await db_session.flush()

    completed = await job_repo.get_by_id(job.id)
    assert completed is not None
    assert completed.status == AcquisitionJobStatus.COMPLETED
    assert completed.dataset_id == dataset_id
    assert len(completed.provenance) == 3

    jobs_for_tenant = await job_repo.list_by_tenant(tenant_id)
    assert [j.id for j in jobs_for_tenant] == [job.id]


async def test_gee_acquisition_job_remote_sensing_fields_round_trip(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    source_repo = SqlAlchemyDatasetSourceRepository(db_session)
    job_repo = SqlAlchemyAcquisitionJobRepository(db_session)

    source, _ = DatasetSource.register(
        tenant_id=None,
        name="GEE Sentinel-2 Source",
        provider=DataProvider.GOOGLE_EARTH_ENGINE,
        description="",
        created_by="admin-1",
    )
    await source_repo.save(source)
    await db_session.flush()

    aoi_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    job, _ = AcquisitionJob.schedule(
        tenant_id=tenant_id,
        provider=DataProvider.GOOGLE_EARTH_ENGINE,
        source_reference="sentinel-2-composite",
        format=AcquisitionFormat.GEOTIFF,
        dataset_source_id=source.id,
        declared_crs="EPSG:4326",
        raw_content_base64=None,
        requested_by="analyst-1",
        remote_sensing_source=RemoteSensingSource.SENTINEL_2,
        aoi_id=aoi_id,
        temporal_start=now,
        temporal_end=now,
        requested_preprocessing=(PreprocessingStep.CLOUD_MASKING, PreprocessingStep.AOI_CLIPPING),
        requested_indices=(SpectralIndex.NDVI, SpectralIndex.EVI),
    )
    await job_repo.save(job)
    await db_session.flush()

    job.start()
    job.complete(
        dataset_id=DatasetId.new(),
        applied_preprocessing=(PreprocessingStep.AOI_CLIPPING,),
        extracted_features={"NDVI": 0.42, "EVI": 0.31},
        skipped_features={"LST": "no thermal band"},
    )
    await job_repo.save(job)
    await db_session.flush()

    fetched = await job_repo.get_by_id(job.id)
    assert fetched is not None
    assert fetched.remote_sensing_source == RemoteSensingSource.SENTINEL_2
    assert fetched.aoi_id == aoi_id
    assert fetched.temporal_start is not None
    assert fetched.requested_preprocessing == (
        PreprocessingStep.CLOUD_MASKING,
        PreprocessingStep.AOI_CLIPPING,
    )
    assert fetched.requested_indices == (SpectralIndex.NDVI, SpectralIndex.EVI)
    assert fetched.applied_preprocessing == (PreprocessingStep.AOI_CLIPPING,)
    assert fetched.extracted_features == {"NDVI": 0.42, "EVI": 0.31}
    assert fetched.skipped_features == {"LST": "no thermal band"}
