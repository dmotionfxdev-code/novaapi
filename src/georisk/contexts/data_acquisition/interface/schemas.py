"""Pydantic request/response models — independent of the SQLAlchemy
models and domain entities (Architecture Redesign §9). Same pattern as
every prior context.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from georisk.contexts.data_acquisition.domain.entities import (
    AcquisitionJob,
    Dataset,
    DatasetSource,
    PredictorVariable,
    VariableSelection,
)


class RegisterDatasetSourceRequest(BaseModel):
    name: str
    provider: str
    description: str = ""


class DatasetSourceResponse(BaseModel):
    id: str
    tenant_id: str | None
    name: str
    provider: str
    description: str
    is_active: bool
    created_by: str
    created_at: datetime

    @classmethod
    def from_domain(cls, source: DatasetSource) -> DatasetSourceResponse:
        return cls(
            id=str(source.id),
            tenant_id=str(source.tenant_id) if source.tenant_id is not None else None,
            name=source.name,
            provider=source.provider.value,
            description=source.description,
            is_active=source.is_active,
            created_by=source.created_by,
            created_at=source.created_at,
        )


class DatasetSourceListResponse(BaseModel):
    data: list[DatasetSourceResponse]

    @classmethod
    def from_domain(cls, sources: list[DatasetSource]) -> DatasetSourceListResponse:
        return cls(data=[DatasetSourceResponse.from_domain(s) for s in sources])


class CatalogDatasetRequest(BaseModel):
    dataset_source_id: str
    name: str
    dataset_type: str
    source: str
    provider: str
    acquisition_date: date
    crs: str = "EPSG:4326"
    spatial_coverage: str
    temporal_coverage_start: datetime
    temporal_coverage_end: datetime
    processing_method: str = "RAW"
    spatial_resolution_m: float | None = None
    temporal_resolution: str | None = None
    model_used: str | None = None
    is_mlr_ready: bool = False
    is_correlation_ready: bool = False


class ReviseDatasetRequest(BaseModel):
    dataset_type: str
    source: str
    provider: str
    acquisition_date: date
    crs: str = "EPSG:4326"
    spatial_coverage: str
    temporal_coverage_start: datetime
    temporal_coverage_end: datetime
    processing_method: str = "RAW"
    description: str
    spatial_resolution_m: float | None = None
    temporal_resolution: str | None = None
    model_used: str | None = None
    is_mlr_ready: bool = False
    is_correlation_ready: bool = False


class ProvenanceEntryResponse(BaseModel):
    timestamp: datetime
    actor: str
    action: str
    description: str
    source_reference: str | None


class DatasetResponse(BaseModel):
    id: str
    tenant_id: str
    dataset_source_id: str
    version: int
    status: str
    name: str
    dataset_type: str
    source: str
    provider: str
    acquisition_date: date
    spatial_resolution_m: float | None
    temporal_resolution: str | None
    crs: str
    spatial_coverage: str
    temporal_coverage_start: datetime
    temporal_coverage_end: datetime
    processing_method: str
    model_used: str | None
    readiness: list[str]
    provenance: list[ProvenanceEntryResponse]
    catalogued_by: str
    created_at: datetime

    @classmethod
    def from_domain(cls, dataset: Dataset) -> DatasetResponse:
        metadata = dataset.metadata
        return cls(
            id=str(dataset.id),
            tenant_id=str(dataset.tenant_id),
            dataset_source_id=str(dataset.dataset_source_id),
            version=dataset.version,
            status=dataset.status.value,
            name=metadata.name,
            dataset_type=metadata.dataset_type.value,
            source=metadata.source,
            provider=metadata.provider.value,
            acquisition_date=metadata.acquisition_date,
            spatial_resolution_m=metadata.spatial_resolution_m,
            temporal_resolution=(
                metadata.temporal_resolution.value if metadata.temporal_resolution else None
            ),
            crs=metadata.crs,
            spatial_coverage=metadata.spatial_coverage,
            temporal_coverage_start=metadata.temporal_coverage.start,
            temporal_coverage_end=metadata.temporal_coverage.end,
            processing_method=metadata.processing_method.value,
            model_used=metadata.model_used,
            readiness=sorted(tag.value for tag in dataset.readiness),
            provenance=[
                ProvenanceEntryResponse(
                    timestamp=p.timestamp,
                    actor=p.actor,
                    action=p.action,
                    description=p.description,
                    source_reference=p.source_reference,
                )
                for p in dataset.provenance
            ],
            catalogued_by=dataset.catalogued_by,
            created_at=dataset.created_at,
        )


class DatasetListResponse(BaseModel):
    data: list[DatasetResponse]

    @classmethod
    def from_domain(cls, datasets: list[Dataset]) -> DatasetListResponse:
        return cls(data=[DatasetResponse.from_domain(d) for d in datasets])


class RegisterPredictorVariableRequest(BaseModel):
    name: str
    code: str
    category: str
    variable_role: str
    data_type: str
    unit: str = ""
    value_min: float | None = None
    value_max: float | None = None
    is_required_for_mlr: bool = False
    linked_dataset_id: str | None = None


class PredictorVariableResponse(BaseModel):
    id: str
    tenant_id: str | None
    name: str
    code: str
    category: str
    variable_role: str
    data_type: str
    unit: str
    value_min: float | None
    value_max: float | None
    is_required_for_mlr: bool
    linked_dataset_id: str | None
    is_active: bool
    created_by: str
    created_at: datetime

    @classmethod
    def from_domain(cls, variable: PredictorVariable) -> PredictorVariableResponse:
        return cls(
            id=str(variable.id),
            tenant_id=str(variable.tenant_id) if variable.tenant_id is not None else None,
            name=variable.name,
            code=variable.code,
            category=variable.category.value,
            variable_role=variable.variable_role.value,
            data_type=variable.data_type.value,
            unit=variable.unit,
            value_min=variable.value_min,
            value_max=variable.value_max,
            is_required_for_mlr=variable.is_required_for_mlr,
            linked_dataset_id=str(variable.linked_dataset_id)
            if variable.linked_dataset_id is not None
            else None,
            is_active=variable.is_active,
            created_by=variable.created_by,
            created_at=variable.created_at,
        )


class PredictorVariableListResponse(BaseModel):
    data: list[PredictorVariableResponse]

    @classmethod
    def from_domain(cls, variables: list[PredictorVariable]) -> PredictorVariableListResponse:
        return cls(data=[PredictorVariableResponse.from_domain(v) for v in variables])


class CreateVariableSelectionRequest(BaseModel):
    name: str
    hazard_type: str | None = None
    selected_variable_ids: list[str]


class VariableSelectionResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    hazard_type: str | None
    selected_variable_ids: list[str]
    status: str
    created_by: str
    created_at: datetime

    @classmethod
    def from_domain(cls, selection: VariableSelection) -> VariableSelectionResponse:
        return cls(
            id=str(selection.id),
            tenant_id=str(selection.tenant_id),
            name=selection.name,
            hazard_type=selection.hazard_type,
            selected_variable_ids=[str(v) for v in selection.selected_variable_ids],
            status=selection.status.value,
            created_by=selection.created_by,
            created_at=selection.created_at,
        )


class ScheduleAcquisitionJobRequest(BaseModel):
    provider: str
    source_reference: str
    format: str
    dataset_source_id: str
    declared_crs: str = "EPSG:4326"
    raw_content_base64: str | None = None
    # --- Sprint 14: Remote Sensing Integration (GOOGLE_EARTH_ENGINE jobs only) ---
    remote_sensing_source: str | None = None
    aoi_id: str | None = None
    temporal_start: datetime | None = None
    temporal_end: datetime | None = None
    comparison_temporal_start: datetime | None = None
    comparison_temporal_end: datetime | None = None
    requested_preprocessing: list[str] = []
    requested_indices: list[str] = []


class AcquisitionJobResponse(BaseModel):
    id: str
    tenant_id: str
    provider: str
    source_reference: str
    format: str
    dataset_source_id: str
    declared_crs: str
    status: str
    dataset_id: str | None
    error: str | None
    requested_by: str
    provenance: list[ProvenanceEntryResponse]
    scheduled_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    remote_sensing_source: str | None
    aoi_id: str | None
    temporal_start: datetime | None
    temporal_end: datetime | None
    comparison_temporal_start: datetime | None
    comparison_temporal_end: datetime | None
    requested_preprocessing: list[str]
    requested_indices: list[str]
    applied_preprocessing: list[str]
    extracted_features: dict[str, float] | None
    skipped_features: dict[str, str] | None
    shapefile_geometry_type: str | None
    shapefile_feature_count: int | None
    shapefile_bounding_box: tuple[float, float, float, float] | None
    shapefile_crs: str | None
    shapefile_attributes: dict[str, object] | None

    @classmethod
    def from_domain(cls, job: AcquisitionJob) -> AcquisitionJobResponse:
        return cls(
            id=str(job.id),
            tenant_id=str(job.tenant_id),
            provider=job.provider.value,
            source_reference=job.source_reference,
            format=job.format.value,
            dataset_source_id=str(job.dataset_source_id),
            declared_crs=job.declared_crs,
            status=job.status.value,
            dataset_id=str(job.dataset_id) if job.dataset_id is not None else None,
            error=job.error,
            requested_by=job.requested_by,
            provenance=[
                ProvenanceEntryResponse(
                    timestamp=p.timestamp,
                    actor=p.actor,
                    action=p.action,
                    description=p.description,
                    source_reference=p.source_reference,
                )
                for p in job.provenance
            ],
            scheduled_at=job.scheduled_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
            remote_sensing_source=(
                job.remote_sensing_source.value if job.remote_sensing_source is not None else None
            ),
            aoi_id=job.aoi_id,
            temporal_start=job.temporal_start,
            temporal_end=job.temporal_end,
            comparison_temporal_start=job.comparison_temporal_start,
            comparison_temporal_end=job.comparison_temporal_end,
            requested_preprocessing=[step.value for step in job.requested_preprocessing],
            requested_indices=[index.value for index in job.requested_indices],
            applied_preprocessing=[step.value for step in job.applied_preprocessing],
            extracted_features=job.extracted_features,
            skipped_features=job.skipped_features,
            shapefile_geometry_type=job.shapefile_geometry_type,
            shapefile_feature_count=job.shapefile_feature_count,
            shapefile_bounding_box=job.shapefile_bounding_box,
            shapefile_crs=job.shapefile_crs,
            shapefile_attributes=job.shapefile_attributes,
        )


class AcquisitionJobListResponse(BaseModel):
    data: list[AcquisitionJobResponse]

    @classmethod
    def from_domain(cls, jobs: list[AcquisitionJob]) -> AcquisitionJobListResponse:
        return cls(data=[AcquisitionJobResponse.from_domain(j) for j in jobs])
