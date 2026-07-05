"""Command handlers for the Data Acquisition context — one transaction,
one aggregate per handler (Application Layer §9), same shape as every
prior context. Never imports from ``contexts.assessment``/
``contexts.geospatial``/``contexts.analysis``.

Sprint 13 adds ``ScheduleAcquisitionJobHandler`` (requirement #5, Import
Scheduling) and ``ExecuteAcquisitionJobHandler`` — the "Dataset Import
Pipeline" (requirement #3): fetch via the injected ``ProviderRegistry``
-> validate (requirement #4) -> catalog a ``Dataset`` by calling this
same file's existing ``Dataset.catalog()`` classmethod -> complete the
job. ``ExecuteAcquisitionJobHandler`` durably transitions the job to
RUNNING (its own commit) *before* the fetch begins — Sprint 9's ``Report``
DRAFT->FINALIZED two-step lifecycle pattern, generalized — so a crash
mid-pipeline leaves an observable RUNNING row, not silently nothing.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

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
from georisk.contexts.data_acquisition.application.ports import (
    AoiReader,
    FetchResult,
    ProviderRegistry,
    RemoteSensingFetchSpec,
)
from georisk.contexts.data_acquisition.domain.entities import (
    AcquisitionJob,
    Dataset,
    DatasetSource,
    PredictorVariable,
    VariableSelection,
)
from georisk.contexts.data_acquisition.domain.errors import (
    AcquisitionJobNotFoundError,
    DatasetNotFoundError,
    DatasetSourceNotFoundError,
    VariableSelectionNotFoundError,
)
from georisk.contexts.data_acquisition.domain.feature_extraction import extract_features
from georisk.contexts.data_acquisition.domain.validation import validate_dataset_content
from georisk.contexts.data_acquisition.domain.value_objects import (
    AcquisitionFormat,
    AcquisitionJobId,
    DataProvider,
    DatasetId,
    DatasetMetadata,
    DatasetReadinessTag,
    DatasetSourceId,
    DatasetType,
    PredictorVariableId,
    PreprocessingStep,
    ProcessingMethod,
    RemoteSensingSource,
    SpectralIndex,
    TemporalResolution,
    VariableCategory,
    VariableDataType,
    VariableRole,
    VariableSelectionId,
)
from georisk.contexts.data_acquisition.infrastructure.repositories import (
    SqlAlchemyAcquisitionJobRepository,
    SqlAlchemyDatasetRepository,
    SqlAlchemyDatasetSourceRepository,
    SqlAlchemyPredictorVariableRepository,
    SqlAlchemyVariableSelectionRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.db.outbox_writer import append_event
from georisk.shared_kernel.types import DateRange


def _readiness_tags(*, is_mlr_ready: bool, is_correlation_ready: bool) -> frozenset:
    tags = set()
    if is_mlr_ready:
        tags.add(DatasetReadinessTag.MLR_READY)
    if is_correlation_ready:
        tags.add(DatasetReadinessTag.CORRELATION_READY)
    return frozenset(tags)


def _assert_dataset_source_visible_to_tenant(source: DatasetSource, tenant_id: TenantId) -> None:
    """A ``DatasetSource`` is visible to a tenant if it's global
    (``tenant_id=None``, e.g. a public CHIRPS registration) or privately
    owned by that same tenant — the identical visibility rule
    ``list_available`` already applies at the SQL layer (Sprint 7),
    applied here as a single-entity check for handlers that resolve one
    ``DatasetSource`` by ID rather than listing all visible ones.
    ``get_by_id`` has no tenant filter (by design — it's shared with the
    global-lookup case), so any caller resolving a source by ID must call
    this before using it. Fails exactly like "not found" — never
    revealing that a private DatasetSource with this ID exists in a
    *different* tenant (API Resource Model §9), matching every other
    cross-tenant check in this codebase (e.g. Assessment's
    ``_assert_same_tenant``).
    """
    if source.tenant_id is not None and source.tenant_id != tenant_id:
        raise DatasetSourceNotFoundError(f"DatasetSource {source.id} not found")


class RegisterDatasetSourceHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyDatasetSourceRepository(session)

    async def handle(self, command: RegisterDatasetSourceCommand) -> DatasetSource:
        tenant_id = TenantId.from_string(command.tenant_id) if command.tenant_id else None
        source, event = DatasetSource.register(
            tenant_id=tenant_id,
            name=command.name,
            provider=DataProvider(command.provider),
            description=command.description,
            created_by=command.issued_by,
        )
        await self._repo.save(source)
        await append_event(
            self._session,
            aggregate_type="DatasetSource",
            aggregate_id=str(source.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value if tenant_id is not None else None,
        )
        await self._session.commit()
        return source


class CatalogDatasetHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._source_repo = SqlAlchemyDatasetSourceRepository(session)
        self._repo = SqlAlchemyDatasetRepository(session)

    async def handle(self, command: CatalogDatasetCommand) -> Dataset:
        tenant_id = TenantId.from_string(command.tenant_id)
        dataset_source_id = DatasetSourceId.from_string(command.dataset_source_id)
        source = await self._source_repo.get_by_id(dataset_source_id)
        if source is None:
            raise DatasetSourceNotFoundError(f"DatasetSource {dataset_source_id} not found")
        _assert_dataset_source_visible_to_tenant(source, tenant_id)

        metadata = _metadata_from_command(command, name=command.name)
        readiness = _readiness_tags(
            is_mlr_ready=command.is_mlr_ready, is_correlation_ready=command.is_correlation_ready
        )
        dataset, event = Dataset.catalog(
            tenant_id=tenant_id,
            dataset_source_id=dataset_source_id,
            metadata=metadata,
            readiness=readiness,
            catalogued_by=command.issued_by,
        )
        await self._repo.save(dataset)
        await append_event(
            self._session,
            aggregate_type="Dataset",
            aggregate_id=str(dataset.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return dataset


class ReviseDatasetHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyDatasetRepository(session)

    async def handle(self, command: ReviseDatasetCommand) -> Dataset:
        tenant_id = TenantId.from_string(command.tenant_id)
        previous = await self._repo.get_latest(tenant_id, command.dataset_name)
        if previous is None:
            raise DatasetNotFoundError(
                f"No cataloged dataset named {command.dataset_name!r} to revise"
            )

        metadata = _metadata_from_command(command, name=command.dataset_name)
        readiness = _readiness_tags(
            is_mlr_ready=command.is_mlr_ready, is_correlation_ready=command.is_correlation_ready
        )
        dataset, event = Dataset.revise(
            previous=previous,
            metadata=metadata,
            readiness=readiness,
            description=command.description,
            catalogued_by=command.issued_by,
        )
        previous.mark_superseded()
        await self._repo.save(previous)
        await self._repo.save(dataset)
        await append_event(
            self._session,
            aggregate_type="Dataset",
            aggregate_id=str(dataset.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return dataset


def _metadata_from_command(
    command: CatalogDatasetCommand | ReviseDatasetCommand, *, name: str
) -> DatasetMetadata:
    return DatasetMetadata(
        name=name,
        dataset_type=DatasetType(command.dataset_type),
        source=command.source,
        provider=DataProvider(command.provider),
        acquisition_date=command.acquisition_date,
        spatial_resolution_m=command.spatial_resolution_m,
        temporal_resolution=(
            TemporalResolution(command.temporal_resolution)
            if command.temporal_resolution
            else None
        ),
        crs=command.crs,
        spatial_coverage=command.spatial_coverage,
        temporal_coverage=DateRange(
            start=datetime.fromisoformat(command.temporal_coverage_start),
            end=datetime.fromisoformat(command.temporal_coverage_end),
        ),
        processing_method=ProcessingMethod(command.processing_method),
        model_used=command.model_used,
    )


class RegisterPredictorVariableHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyPredictorVariableRepository(session)

    async def handle(self, command: RegisterPredictorVariableCommand) -> PredictorVariable:
        tenant_id = TenantId.from_string(command.tenant_id) if command.tenant_id else None
        linked_dataset_id = (
            DatasetId.from_string(command.linked_dataset_id)
            if command.linked_dataset_id
            else None
        )
        variable, event = PredictorVariable.register(
            tenant_id=tenant_id,
            name=command.name,
            code=command.code,
            category=VariableCategory(command.category),
            variable_role=VariableRole(command.variable_role),
            data_type=VariableDataType(command.data_type),
            unit=command.unit,
            value_min=command.value_min,
            value_max=command.value_max,
            is_required_for_mlr=command.is_required_for_mlr,
            linked_dataset_id=linked_dataset_id,
            created_by=command.issued_by,
        )
        await self._repo.save(variable)
        await append_event(
            self._session,
            aggregate_type="PredictorVariable",
            aggregate_id=str(variable.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value if tenant_id is not None else None,
        )
        await self._session.commit()
        return variable


class CreateVariableSelectionHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyVariableSelectionRepository(session)

    async def handle(self, command: CreateVariableSelectionCommand) -> VariableSelection:
        tenant_id = TenantId.from_string(command.tenant_id)
        selection, event = VariableSelection.create(
            tenant_id=tenant_id,
            name=command.name,
            hazard_type=command.hazard_type,
            selected_variable_ids=tuple(
                PredictorVariableId.from_string(v) for v in command.selected_variable_ids
            ),
            created_by=command.issued_by,
        )
        await self._repo.save(selection)
        await append_event(
            self._session,
            aggregate_type="VariableSelection",
            aggregate_id=str(selection.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return selection


class ConfirmVariableSelectionHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyVariableSelectionRepository(session)

    async def handle(self, command: ConfirmVariableSelectionCommand) -> VariableSelection:
        tenant_id = TenantId.from_string(command.tenant_id)
        selection_id = VariableSelectionId.from_string(command.variable_selection_id)
        selection = await self._repo.get_by_id(selection_id)
        if selection is None or str(selection.tenant_id) != str(tenant_id):
            raise VariableSelectionNotFoundError(f"VariableSelection {selection_id} not found")

        event = selection.confirm()
        await self._repo.save(selection)
        await append_event(
            self._session,
            aggregate_type="VariableSelection",
            aggregate_id=str(selection.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return selection


_DATASET_TYPE_BY_ACQUISITION_FORMAT: dict[AcquisitionFormat, DatasetType] = {
    AcquisitionFormat.GEOJSON: DatasetType.VECTOR,
    AcquisitionFormat.SHAPEFILE: DatasetType.VECTOR,
    AcquisitionFormat.GEOTIFF: DatasetType.RASTER,
    AcquisitionFormat.CSV: DatasetType.TABULAR,
    AcquisitionFormat.JSON: DatasetType.TABULAR,
}


def _metadata_for_completed_job(job: AcquisitionJob) -> DatasetMetadata:
    now = datetime.now(UTC)
    return DatasetMetadata(
        name=job.source_reference,
        dataset_type=_DATASET_TYPE_BY_ACQUISITION_FORMAT[job.format],
        source=f"AcquisitionJob {job.id} via {job.provider.value}",
        provider=job.provider,
        acquisition_date=now.date(),
        spatial_resolution_m=None,
        temporal_resolution=None,
        crs=job.declared_crs,
        spatial_coverage=(
            "Not derived — Sprint 13's Dataset Validation is structural "
            "(format/CRS), not full geospatial extent computation"
        ),
        temporal_coverage=DateRange(start=now, end=now),
        processing_method=ProcessingMethod.RAW,
        model_used=None,
    )


class ScheduleAcquisitionJobHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyAcquisitionJobRepository(session)
        self._source_repo = SqlAlchemyDatasetSourceRepository(session)

    async def handle(self, command: ScheduleAcquisitionJobCommand) -> AcquisitionJob:
        tenant_id = TenantId.from_string(command.tenant_id)
        dataset_source_id = DatasetSourceId.from_string(command.dataset_source_id)
        source = await self._source_repo.get_by_id(dataset_source_id)
        if source is None:
            raise DatasetSourceNotFoundError(f"DatasetSource {dataset_source_id} not found")
        _assert_dataset_source_visible_to_tenant(source, tenant_id)

        job, event = AcquisitionJob.schedule(
            tenant_id=tenant_id,
            provider=DataProvider(command.provider),
            source_reference=command.source_reference,
            format=AcquisitionFormat(command.format),
            dataset_source_id=dataset_source_id,
            declared_crs=command.declared_crs,
            raw_content_base64=command.raw_content_base64,
            requested_by=command.issued_by,
            remote_sensing_source=(
                RemoteSensingSource(command.remote_sensing_source)
                if command.remote_sensing_source
                else None
            ),
            aoi_id=command.aoi_id,
            temporal_start=(
                datetime.fromisoformat(command.temporal_start) if command.temporal_start else None
            ),
            temporal_end=(
                datetime.fromisoformat(command.temporal_end) if command.temporal_end else None
            ),
            comparison_temporal_start=(
                datetime.fromisoformat(command.comparison_temporal_start)
                if command.comparison_temporal_start
                else None
            ),
            comparison_temporal_end=(
                datetime.fromisoformat(command.comparison_temporal_end)
                if command.comparison_temporal_end
                else None
            ),
            requested_preprocessing=tuple(
                PreprocessingStep(step) for step in command.requested_preprocessing
            ),
            requested_indices=tuple(
                SpectralIndex(index) for index in command.requested_indices
            ),
        )
        await self._repo.save(job)
        await append_event(
            self._session,
            aggregate_type="AcquisitionJob",
            aggregate_id=str(job.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return job


class ExecuteAcquisitionJobHandler:
    """The Dataset Import Pipeline (requirement #3): fetch -> validate
    (requirement #4) -> catalog. ``provider_registry`` is injected rather
    than constructed here — the same composition-root pattern every other
    externally-configured collaborator in this codebase (channels,
    strategies, readers) is wired through, so this handler never
    hardcodes which concrete adapter backs which ``DataProvider``.
    """

    def __init__(
        self, session: AsyncSession, provider_registry: ProviderRegistry, aoi_reader: AoiReader
    ) -> None:
        self._session = session
        self._registry = provider_registry
        self._aoi_reader = aoi_reader
        self._job_repo = SqlAlchemyAcquisitionJobRepository(session)
        self._dataset_repo = SqlAlchemyDatasetRepository(session)

    async def handle(self, command: ExecuteAcquisitionJobCommand) -> AcquisitionJob:
        tenant_id = TenantId.from_string(command.tenant_id)
        job_id = AcquisitionJobId.from_string(command.acquisition_job_id)
        job = await self._job_repo.get_by_id(job_id)
        if job is None or str(job.tenant_id) != str(tenant_id):
            raise AcquisitionJobNotFoundError(f"AcquisitionJob {job_id} not found")

        started_event = job.start()
        await self._job_repo.save(job)
        await append_event(
            self._session,
            aggregate_type="AcquisitionJob",
            aggregate_id=str(job.id),
            event_type=started_event.event_type,
            payload=started_event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()

        # Sprint 14 requirement #5 (AOI-based Processing): resolve the
        # AOI's real geometry BEFORE calling any provider — the handler
        # is the one place allowed to read Geospatial (via the injected
        # composition-root ``AoiReader``); providers only ever see a
        # plain GeoJSON dict, never a typed Geospatial ID/entity.
        aoi_geometry: dict | None = None
        if job.aoi_id is not None:
            aoi_info = await self._aoi_reader.get_aoi_geometry(
                tenant_id=tenant_id, aoi_id=job.aoi_id
            )
            if aoi_info is None:
                return await self._fail(
                    job, tenant_id, f"AreaOfInterest {job.aoi_id} not found"
                )
            aoi_geometry = aoi_info.geometry

        raw_content = (
            base64.b64decode(job.raw_content_base64) if job.raw_content_base64 else None
        )
        spec = RemoteSensingFetchSpec(
            remote_sensing_source=job.remote_sensing_source,
            declared_crs=job.declared_crs,
            temporal_start=job.temporal_start,
            temporal_end=job.temporal_end,
            comparison_temporal_start=job.comparison_temporal_start,
            comparison_temporal_end=job.comparison_temporal_end,
            aoi_geometry=aoi_geometry,
            requested_preprocessing=job.requested_preprocessing,
        )
        try:
            provider_adapter = self._registry.resolve(job.provider)
            fetch_result = await provider_adapter.fetch(
                source_reference=job.source_reference, raw_content=raw_content, spec=spec
            )
        except Exception as exc:  # noqa: BLE001 — an untrusted provider
            # adapter (real HTTP/GEE, or a misbehaving future registrant)
            # is exactly the "isolate an untrusted boundary" case every
            # prior handler that calls out to an injected collaborator
            # already applies — a raised exception here becomes a
            # recorded FAILED job, not a 500 that loses the job's state
            # entirely.
            fetch_result = FetchResult(success=False, content=None, error=str(exc))

        if not fetch_result.success or fetch_result.content is None:
            return await self._fail(job, tenant_id, fetch_result.error or "Fetch failed")

        outcome = validate_dataset_content(
            format=job.format, content=fetch_result.content, crs=job.declared_crs
        )
        if not outcome.is_valid:
            return await self._fail(job, tenant_id, "; ".join(outcome.errors))

        # Sprint 14 requirement #4 (Feature Extraction Pipeline): only
        # runs when the job actually asked for indices AND the provider
        # actually returned AOI-aggregate band statistics (only
        # ``GoogleEarthEngineProvider`` ever populates
        # ``fetch_result.band_statistics`` — Local Upload/HTTP jobs never
        # request indices in the first place, since ``requested_indices``
        # is only meaningful for a ``remote_sensing_source``-bearing job).
        computed_features: dict[str, float] = {}
        skipped_features: dict[str, str] = {}
        if job.requested_indices and job.remote_sensing_source is not None:
            if fetch_result.band_statistics is not None:
                computed_features, skipped_features = extract_features(
                    source=job.remote_sensing_source,
                    band_statistics=fetch_result.band_statistics,
                    requested_indices=job.requested_indices,
                    comparison_band_statistics=fetch_result.comparison_band_statistics,
                )
            else:
                skipped_features = {
                    index.value: "provider returned no band statistics"
                    for index in job.requested_indices
                }

        metadata = _metadata_for_completed_job(job)
        dataset, catalogued_event = Dataset.catalog(
            tenant_id=tenant_id,
            dataset_source_id=job.dataset_source_id,
            metadata=metadata,
            readiness=frozenset(),
            catalogued_by=job.requested_by,
        )
        await self._dataset_repo.save(dataset)
        await append_event(
            self._session,
            aggregate_type="Dataset",
            aggregate_id=str(dataset.id),
            event_type=catalogued_event.event_type,
            payload=catalogued_event.payload(),
            tenant_id=tenant_id.value,
        )

        completed_event = job.complete(
            dataset_id=dataset.id,
            applied_preprocessing=fetch_result.applied_preprocessing,
            extracted_features=computed_features or None,
            skipped_features=skipped_features or None,
        )
        await self._job_repo.save(job)
        await append_event(
            self._session,
            aggregate_type="AcquisitionJob",
            aggregate_id=str(job.id),
            event_type=completed_event.event_type,
            payload=completed_event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return job

    async def _fail(self, job: AcquisitionJob, tenant_id: TenantId, error: str) -> AcquisitionJob:
        failed_event = job.fail(error=error)
        await self._job_repo.save(job)
        await append_event(
            self._session,
            aggregate_type="AcquisitionJob",
            aggregate_id=str(job.id),
            event_type=failed_event.event_type,
            payload=failed_event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return job
