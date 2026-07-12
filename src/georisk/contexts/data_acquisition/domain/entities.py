"""The Data Acquisition context's aggregate roots for Sprint 7's catalog/
registry scope: ``DatasetSource`` (registry — requirement #6),
``Dataset`` (catalog + metadata + provenance + versioning — requirements
#1/#2/#3/#5), ``PredictorVariable`` (registry — requirement #7), and
``VariableSelection`` (requirement #8). Nothing here imports from
``contexts.assessment``/``contexts.geospatial``/``contexts.analysis`` —
structurally enforced by the import-linter's peer-independence contract.

Sprint 13 adds ``AcquisitionJob`` — the "go fetch real data" aggregate
Sprint 7's docstring explicitly deferred. Its SCHEDULED -> RUNNING ->
COMPLETED/FAILED lifecycle mirrors ``AlertRule``/``NotificationSubscription``
(Sprint 11)'s mutable-update-in-place pattern (one row, transitioned in
place) rather than ``Dataset``'s write-once-per-version pattern, since an
acquisition job is a single unit of work, not a versioned catalog entry —
though its terminal ``complete()`` step catalogs a brand-new ``Dataset``
by calling this same file's ``Dataset.catalog()`` classmethod directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from georisk.contexts.data_acquisition.domain.errors import (
    IllegalAcquisitionJobTransitionError,
    InvalidAcquisitionJobError,
    InvalidVariableSelectionError,
)
from georisk.contexts.data_acquisition.domain.events import (
    AcquisitionJobCompleted,
    AcquisitionJobFailed,
    AcquisitionJobScheduled,
    AcquisitionJobStarted,
    DatasetCatalogued,
    DatasetRevised,
    DatasetSourceRegistered,
    PredictorVariableRegistered,
    VariableSelectionConfirmed,
    VariableSelectionCreated,
)
from georisk.contexts.data_acquisition.domain.value_objects import (
    ACQUISITION_CAPABLE_PROVIDERS,
    AcquisitionFormat,
    AcquisitionJobId,
    AcquisitionJobStatus,
    DataProvider,
    DatasetId,
    DatasetMetadata,
    DatasetReadinessTag,
    DatasetSourceId,
    DatasetStatus,
    PredictorVariableId,
    PreprocessingStep,
    ProvenanceEntry,
    RemoteSensingSource,
    SpectralIndex,
    VariableCategory,
    VariableDataType,
    VariableRole,
    VariableSelectionId,
    VariableSelectionStatus,
)
from georisk.contexts.identity.domain.value_objects import TenantId


@dataclass(slots=True)
class DatasetSource:
    """Domain Model §1 row 5 — "reference/catalog aggregate; provider
    identity is unique per tenant scope (or global for public sources)."
    ``tenant_id`` is ``None`` for a platform-wide source every tenant can
    reference (e.g. a public CHIRPS registration); set for a
    tenant-private source (e.g. a tenant's own upload pipeline).
    """

    id: DatasetSourceId
    tenant_id: TenantId | None
    name: str
    provider: DataProvider
    description: str
    is_active: bool
    created_by: str
    created_at: datetime

    @classmethod
    def register(
        cls,
        *,
        tenant_id: TenantId | None,
        name: str,
        provider: DataProvider,
        description: str,
        created_by: str,
    ) -> tuple[DatasetSource, DatasetSourceRegistered]:
        source = cls(
            id=DatasetSourceId.new(),
            tenant_id=tenant_id,
            name=name,
            provider=provider,
            description=description,
            is_active=True,
            created_by=created_by,
            created_at=datetime.now(UTC),
        )
        event = DatasetSourceRegistered(
            dataset_source_id=str(source.id),
            tenant_id=str(tenant_id) if tenant_id is not None else None,
            name=name,
            provider=provider.value,
        )
        return source, event

    def deactivate(self) -> None:
        self.is_active = False


@dataclass(slots=True)
class Dataset:
    """Requirements #1 (Catalog), #2 (Metadata Framework), #3 (Provenance
    Tracking), #5 (Versioning). Write-once-per-version, same immutability
    discipline as ``StageResult``/``AreaOfInterest`` — a revision creates
    a new row via ``revise()`` and flips the previous version to
    ``SUPERSEDED`` via ``mark_superseded()``; nothing mutates the
    metadata of an existing version in place.
    """

    id: DatasetId
    tenant_id: TenantId
    dataset_source_id: DatasetSourceId
    version: int
    status: DatasetStatus
    metadata: DatasetMetadata
    provenance: tuple[ProvenanceEntry, ...]
    readiness: frozenset[DatasetReadinessTag]
    catalogued_by: str
    created_at: datetime

    @classmethod
    def catalog(
        cls,
        *,
        tenant_id: TenantId,
        dataset_source_id: DatasetSourceId,
        metadata: DatasetMetadata,
        readiness: frozenset[DatasetReadinessTag],
        catalogued_by: str,
    ) -> tuple[Dataset, DatasetCatalogued]:
        provenance = (
            ProvenanceEntry.now(
                actor=catalogued_by,
                action="CATALOGUED",
                description=f"Initial cataloguing of {metadata.name!r}",
            ),
        )
        dataset = cls(
            id=DatasetId.new(),
            tenant_id=tenant_id,
            dataset_source_id=dataset_source_id,
            version=1,
            status=DatasetStatus.CATALOGUED,
            metadata=metadata,
            provenance=provenance,
            readiness=readiness,
            catalogued_by=catalogued_by,
            created_at=datetime.now(UTC),
        )
        event = DatasetCatalogued(
            dataset_id=str(dataset.id),
            tenant_id=str(tenant_id),
            name=metadata.name,
            version=dataset.version,
        )
        return dataset, event

    @classmethod
    def revise(
        cls,
        *,
        previous: Dataset,
        metadata: DatasetMetadata,
        readiness: frozenset[DatasetReadinessTag],
        description: str,
        catalogued_by: str,
    ) -> tuple[Dataset, DatasetRevised]:
        provenance = (
            *previous.provenance,
            ProvenanceEntry.now(
                actor=catalogued_by,
                action="REVISED",
                description=description,
                source_reference=str(previous.id),
            ),
        )
        dataset = cls(
            id=DatasetId.new(),
            tenant_id=previous.tenant_id,
            dataset_source_id=previous.dataset_source_id,
            version=previous.version + 1,
            status=DatasetStatus.CATALOGUED,
            metadata=metadata,
            provenance=provenance,
            readiness=readiness,
            catalogued_by=catalogued_by,
            created_at=datetime.now(UTC),
        )
        event = DatasetRevised(
            dataset_id=str(dataset.id),
            tenant_id=str(previous.tenant_id),
            version=dataset.version,
            superseded_dataset_id=str(previous.id),
        )
        return dataset, event

    def mark_superseded(self) -> None:
        self.status = DatasetStatus.SUPERSEDED


@dataclass(slots=True)
class PredictorVariable:
    """Requirement #7 — the Predictor Variable Registry. Generalizes the
    legacy ``UserVariable`` (Domain Model §1 row 9's ``VariableDefinition``)
    with the category/required-for-MLR structure every hazard's MLR
    variable list already needs (confirmed against both FIRAS's and
    WRRAS's ``mlr.py`` variable tables).
    """

    id: PredictorVariableId
    tenant_id: TenantId | None
    name: str
    code: str
    category: VariableCategory
    variable_role: VariableRole
    data_type: VariableDataType
    unit: str
    value_min: float | None
    value_max: float | None
    is_required_for_mlr: bool
    linked_dataset_id: DatasetId | None
    is_active: bool
    created_by: str
    created_at: datetime

    @classmethod
    def register(
        cls,
        *,
        tenant_id: TenantId | None,
        name: str,
        code: str,
        category: VariableCategory,
        variable_role: VariableRole,
        data_type: VariableDataType,
        unit: str,
        value_min: float | None,
        value_max: float | None,
        is_required_for_mlr: bool,
        linked_dataset_id: DatasetId | None,
        created_by: str,
    ) -> tuple[PredictorVariable, PredictorVariableRegistered]:
        variable = cls(
            id=PredictorVariableId.new(),
            tenant_id=tenant_id,
            name=name,
            code=code,
            category=category,
            variable_role=variable_role,
            data_type=data_type,
            unit=unit,
            value_min=value_min,
            value_max=value_max,
            is_required_for_mlr=is_required_for_mlr,
            linked_dataset_id=linked_dataset_id,
            is_active=True,
            created_by=created_by,
            created_at=datetime.now(UTC),
        )
        event = PredictorVariableRegistered(
            predictor_variable_id=str(variable.id),
            tenant_id=str(tenant_id) if tenant_id is not None else None,
            name=name,
            category=category.value,
        )
        return variable, event

    def deactivate(self) -> None:
        self.is_active = False


@dataclass(slots=True)
class VariableSelection:
    """Requirement #8 — the Variable Selection Framework: "user-selectable
    predictor variables" persisted as a named, reusable selection rather
    than an ephemeral request parameter, so a later Prediction Engine
    sprint can read back exactly which variables a given analysis run was
    configured with.
    """

    id: VariableSelectionId
    tenant_id: TenantId
    name: str
    hazard_type: str | None
    selected_variable_ids: tuple[PredictorVariableId, ...]
    status: VariableSelectionStatus
    created_by: str
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        tenant_id: TenantId,
        name: str,
        hazard_type: str | None,
        selected_variable_ids: tuple[PredictorVariableId, ...],
        created_by: str,
    ) -> tuple[VariableSelection, VariableSelectionCreated]:
        if not selected_variable_ids:
            raise InvalidVariableSelectionError(
                "VariableSelection must select at least one PredictorVariable"
            )
        selection = cls(
            id=VariableSelectionId.new(),
            tenant_id=tenant_id,
            name=name,
            hazard_type=hazard_type,
            selected_variable_ids=selected_variable_ids,
            status=VariableSelectionStatus.DRAFT,
            created_by=created_by,
            created_at=datetime.now(UTC),
        )
        event = VariableSelectionCreated(
            variable_selection_id=str(selection.id),
            tenant_id=str(tenant_id),
            name=name,
            variable_count=len(selected_variable_ids),
        )
        return selection, event

    def confirm(self) -> VariableSelectionConfirmed:
        self.status = VariableSelectionStatus.CONFIRMED
        return VariableSelectionConfirmed(
            variable_selection_id=str(self.id), tenant_id=str(self.tenant_id)
        )


@dataclass(slots=True)
class AcquisitionJob:
    """Requirements #1 (Aggregate), #5 (Import Scheduling), #6 (Provenance
    Tracking). ``dataset_source_id`` names which registered
    ``DatasetSource`` this job's fetch is attributed to (the same registry
    ``Dataset.catalog()`` already requires); ``raw_content_base64`` is
    populated only for ``DataProvider.LOCAL_UPLOAD`` jobs — the uploaded
    bytes, base64-encoded, carried on the job itself since no object-
    storage integration exists yet in this platform (``storage_backend``
    settings are declared but unused by any context so far) and adding one
    is out of this sprint's scope.
    """

    id: AcquisitionJobId
    tenant_id: TenantId
    provider: DataProvider
    source_reference: str
    format: AcquisitionFormat
    dataset_source_id: DatasetSourceId
    declared_crs: str
    status: AcquisitionJobStatus
    raw_content_base64: str | None
    provenance: tuple[ProvenanceEntry, ...]
    dataset_id: DatasetId | None
    error: str | None
    requested_by: str
    scheduled_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    # --- Sprint 14: Remote Sensing Integration, all additive/optional so
    # every Sprint 13 (non-GEE) job leaves these at their "not applicable"
    # defaults. ---
    remote_sensing_source: RemoteSensingSource | None
    aoi_id: str | None
    temporal_start: datetime | None
    temporal_end: datetime | None
    comparison_temporal_start: datetime | None
    comparison_temporal_end: datetime | None
    requested_preprocessing: tuple[PreprocessingStep, ...]
    requested_indices: tuple[SpectralIndex, ...]
    applied_preprocessing: tuple[PreprocessingStep, ...]
    extracted_features: dict[str, float] | None
    skipped_features: dict[str, str] | None
    # --- Sprint B: real ESRI Shapefile ingestion, all additive/optional so
    # every non-Shapefile job (and every Sprint 13/14 job that predates
    # this sprint) leaves these at their "not applicable" defaults. ---
    shapefile_geometry_type: str | None
    shapefile_feature_count: int | None
    shapefile_bounding_box: tuple[float, float, float, float] | None
    shapefile_crs: str | None
    shapefile_attributes: dict[str, object] | None

    @classmethod
    def schedule(
        cls,
        *,
        tenant_id: TenantId,
        provider: DataProvider,
        source_reference: str,
        format: AcquisitionFormat,
        dataset_source_id: DatasetSourceId,
        declared_crs: str,
        raw_content_base64: str | None,
        requested_by: str,
        remote_sensing_source: RemoteSensingSource | None = None,
        aoi_id: str | None = None,
        temporal_start: datetime | None = None,
        temporal_end: datetime | None = None,
        comparison_temporal_start: datetime | None = None,
        comparison_temporal_end: datetime | None = None,
        requested_preprocessing: tuple[PreprocessingStep, ...] = (),
        requested_indices: tuple[SpectralIndex, ...] = (),
    ) -> tuple[AcquisitionJob, AcquisitionJobScheduled]:
        if provider not in ACQUISITION_CAPABLE_PROVIDERS:
            raise InvalidAcquisitionJobError(
                f"DataProvider {provider} is not an acquisition-capable provider "
                f"(must be one of {sorted(p.value for p in ACQUISITION_CAPABLE_PROVIDERS)})"
            )
        if provider == DataProvider.LOCAL_UPLOAD and not raw_content_base64:
            raise InvalidAcquisitionJobError(
                "LOCAL_UPLOAD acquisition jobs require raw_content_base64"
            )
        if provider == DataProvider.GOOGLE_EARTH_ENGINE and remote_sensing_source is None:
            raise InvalidAcquisitionJobError(
                "GOOGLE_EARTH_ENGINE acquisition jobs require remote_sensing_source"
            )
        if provider == DataProvider.GOOGLE_EARTH_ENGINE and aoi_id is None:
            raise InvalidAcquisitionJobError(
                "GOOGLE_EARTH_ENGINE acquisition jobs require an aoi_id — reduceRegion/"
                "getDownloadURL both need a bounded region, and an unbounded global "
                "export is not something this platform allows silently"
            )
        now = datetime.now(UTC)
        job = cls(
            id=AcquisitionJobId.new(),
            tenant_id=tenant_id,
            provider=provider,
            source_reference=source_reference,
            format=format,
            dataset_source_id=dataset_source_id,
            declared_crs=declared_crs,
            status=AcquisitionJobStatus.SCHEDULED,
            raw_content_base64=raw_content_base64,
            provenance=(
                ProvenanceEntry.now(
                    actor=requested_by,
                    action="SCHEDULED",
                    description=f"Acquisition scheduled from {provider.value}",
                    source_reference=source_reference,
                ),
            ),
            dataset_id=None,
            error=None,
            requested_by=requested_by,
            scheduled_at=now,
            started_at=None,
            completed_at=None,
            remote_sensing_source=remote_sensing_source,
            aoi_id=aoi_id,
            temporal_start=temporal_start,
            temporal_end=temporal_end,
            comparison_temporal_start=comparison_temporal_start,
            comparison_temporal_end=comparison_temporal_end,
            requested_preprocessing=requested_preprocessing,
            requested_indices=requested_indices,
            applied_preprocessing=(),
            extracted_features=None,
            skipped_features=None,
            shapefile_geometry_type=None,
            shapefile_feature_count=None,
            shapefile_bounding_box=None,
            shapefile_crs=None,
            shapefile_attributes=None,
        )
        event = AcquisitionJobScheduled(
            acquisition_job_id=str(job.id),
            tenant_id=str(tenant_id),
            provider=provider.value,
            format=format.value,
        )
        return job, event

    def start(self) -> AcquisitionJobStarted:
        if self.status != AcquisitionJobStatus.SCHEDULED:
            raise IllegalAcquisitionJobTransitionError(
                f"Cannot start AcquisitionJob {self.id} from status {self.status}"
            )
        self.status = AcquisitionJobStatus.RUNNING
        self.started_at = datetime.now(UTC)
        self.provenance = (
            *self.provenance,
            ProvenanceEntry.now(actor="system", action="STARTED", description="Fetch started"),
        )
        return AcquisitionJobStarted(acquisition_job_id=str(self.id), tenant_id=str(self.tenant_id))

    def complete(
        self,
        *,
        dataset_id: DatasetId,
        applied_preprocessing: tuple[PreprocessingStep, ...] = (),
        extracted_features: dict[str, float] | None = None,
        skipped_features: dict[str, str] | None = None,
        shapefile_geometry_type: str | None = None,
        shapefile_feature_count: int | None = None,
        shapefile_bounding_box: tuple[float, float, float, float] | None = None,
        shapefile_crs: str | None = None,
        shapefile_attributes: dict[str, object] | None = None,
        shapefile_importer_version: str | None = None,
        raster_download_warning: str | None = None,
    ) -> AcquisitionJobCompleted:
        if self.status != AcquisitionJobStatus.RUNNING:
            raise IllegalAcquisitionJobTransitionError(
                f"Cannot complete AcquisitionJob {self.id} from status {self.status}"
            )
        self.status = AcquisitionJobStatus.COMPLETED
        self.completed_at = datetime.now(UTC)
        self.dataset_id = dataset_id
        self.applied_preprocessing = applied_preprocessing
        self.extracted_features = extracted_features
        self.skipped_features = skipped_features
        self.shapefile_geometry_type = shapefile_geometry_type
        self.shapefile_feature_count = shapefile_feature_count
        self.shapefile_bounding_box = shapefile_bounding_box
        self.shapefile_crs = shapefile_crs
        self.shapefile_attributes = shapefile_attributes
        description = "Fetched, validated, and catalogued successfully"
        if extracted_features:
            description += f"; extracted features: {sorted(extracted_features)}"
        if raster_download_warning is not None:
            # Bug fix (post-RC1 Production Acceptance Test) — requirement
            # #4: a durable, queryable provenance record of the raster
            # download being intentionally skipped, same mechanism as
            # every other provenance note on this entity (never a
            # separate ad hoc log-only warning).
            description += f"; WARNING: {raster_download_warning}"
        if shapefile_geometry_type is not None:
            # Sprint B requirement #5 — Provenance: original filename
            # (``source_reference``), CRS, geometry type, feature count,
            # bounding box, and importer version, all recorded via this
            # existing ``ProvenanceEntry``, timestamped by
            # ``ProvenanceEntry.now()`` below (the "upload timestamp").
            description += (
                f"; Shapefile import: file={self.source_reference!r}, "
                f"geometry_type={shapefile_geometry_type}, "
                f"features={shapefile_feature_count}, crs={shapefile_crs}, "
                f"bbox={shapefile_bounding_box}, importer={shapefile_importer_version}"
            )
        self.provenance = (
            *self.provenance,
            ProvenanceEntry.now(
                actor="system",
                action="COMPLETED",
                description=description,
                source_reference=str(dataset_id),
            ),
        )
        return AcquisitionJobCompleted(
            acquisition_job_id=str(self.id),
            tenant_id=str(self.tenant_id),
            dataset_id=str(dataset_id),
        )

    def fail(self, *, error: str) -> AcquisitionJobFailed:
        if self.status != AcquisitionJobStatus.RUNNING:
            raise IllegalAcquisitionJobTransitionError(
                f"Cannot fail AcquisitionJob {self.id} from status {self.status}"
            )
        self.status = AcquisitionJobStatus.FAILED
        self.completed_at = datetime.now(UTC)
        self.error = error
        self.provenance = (
            *self.provenance,
            ProvenanceEntry.now(actor="system", action="FAILED", description=error),
        )
        return AcquisitionJobFailed(
            acquisition_job_id=str(self.id), tenant_id=str(self.tenant_id), error=error
        )
