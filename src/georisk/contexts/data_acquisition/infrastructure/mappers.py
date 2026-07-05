"""Maps between Data Acquisition's domain entities and their SQLAlchemy
ORM representations. Free functions, not methods on either side (same
pattern as every prior context).
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import datetime

from georisk.contexts.data_acquisition.domain.entities import (
    AcquisitionJob,
    Dataset,
    DatasetSource,
    PredictorVariable,
    VariableSelection,
)
from georisk.contexts.data_acquisition.domain.value_objects import (
    AcquisitionFormat,
    AcquisitionJobId,
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
    ProvenanceEntry,
    RemoteSensingSource,
    SpectralIndex,
    TemporalResolution,
    VariableCategory,
    VariableDataType,
    VariableRole,
    VariableSelectionId,
    VariableSelectionStatus,
)
from georisk.contexts.data_acquisition.infrastructure.models import (
    AcquisitionJobModel,
    DatasetModel,
    DatasetSourceModel,
    PredictorVariableModel,
    VariableSelectionModel,
)
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.shared_kernel.types import DateRange


def dataset_source_to_domain(model: DatasetSourceModel) -> DatasetSource:
    return DatasetSource(
        id=DatasetSourceId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id) if model.tenant_id else None,
        name=model.name,
        provider=DataProvider(model.provider),
        description=model.description,
        is_active=model.is_active,
        created_by=model.created_by,
        created_at=model.created_at,
    )


def apply_dataset_source_to_model(entity: DatasetSource, model: DatasetSourceModel) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value if entity.tenant_id is not None else None
    model.name = entity.name
    model.provider = entity.provider.value
    model.description = entity.description
    model.is_active = entity.is_active
    model.created_by = entity.created_by
    model.created_at = entity.created_at


def dataset_to_domain(model: DatasetModel) -> Dataset:
    metadata = DatasetMetadata(
        name=model.metadata_name,
        dataset_type=DatasetType(model.dataset_type),
        source=model.source,
        provider=DataProvider(model.provider),
        acquisition_date=model.acquisition_date,
        spatial_resolution_m=model.spatial_resolution_m,
        temporal_resolution=(
            TemporalResolution(model.temporal_resolution) if model.temporal_resolution else None
        ),
        crs=model.crs,
        spatial_coverage=model.spatial_coverage,
        temporal_coverage=DateRange(
            start=model.temporal_coverage_start, end=model.temporal_coverage_end
        ),
        processing_method=ProcessingMethod(model.processing_method),
        model_used=model.model_used,
    )
    return Dataset(
        id=DatasetId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        dataset_source_id=DatasetSourceId(value=model.dataset_source_id),
        version=model.version,
        status=DatasetStatus(model.status),
        metadata=metadata,
        provenance=tuple(
            ProvenanceEntry(
                timestamp=datetime.fromisoformat(p["timestamp"]),
                actor=p["actor"],
                action=p["action"],
                description=p["description"],
                source_reference=p.get("source_reference"),
            )
            for p in model.provenance
        ),
        readiness=frozenset(DatasetReadinessTag(tag) for tag in model.readiness),
        catalogued_by=model.catalogued_by,
        created_at=model.created_at,
    )


def apply_dataset_to_model(entity: Dataset, model: DatasetModel) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.dataset_source_id = entity.dataset_source_id.value
    model.version = entity.version
    model.status = entity.status.value

    metadata = entity.metadata
    model.metadata_name = metadata.name
    model.dataset_type = metadata.dataset_type.value
    model.source = metadata.source
    model.provider = metadata.provider.value
    model.acquisition_date = metadata.acquisition_date
    model.spatial_resolution_m = metadata.spatial_resolution_m
    model.temporal_resolution = (
        metadata.temporal_resolution.value if metadata.temporal_resolution else None
    )
    model.crs = metadata.crs
    model.spatial_coverage = metadata.spatial_coverage
    model.temporal_coverage_start = metadata.temporal_coverage.start
    model.temporal_coverage_end = metadata.temporal_coverage.end
    model.processing_method = metadata.processing_method.value
    model.model_used = metadata.model_used

    model.provenance = [
        {
            "timestamp": entry.timestamp.isoformat(),
            "actor": entry.actor,
            "action": entry.action,
            "description": entry.description,
            "source_reference": entry.source_reference,
        }
        for entry in entity.provenance
    ]
    model.readiness = sorted(tag.value for tag in entity.readiness)
    model.catalogued_by = entity.catalogued_by
    model.created_at = entity.created_at


def predictor_variable_to_domain(model: PredictorVariableModel) -> PredictorVariable:
    return PredictorVariable(
        id=PredictorVariableId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id) if model.tenant_id else None,
        name=model.name,
        code=model.code,
        category=VariableCategory(model.category),
        variable_role=VariableRole(model.variable_role),
        data_type=VariableDataType(model.data_type),
        unit=model.unit,
        value_min=model.value_min,
        value_max=model.value_max,
        is_required_for_mlr=model.is_required_for_mlr,
        linked_dataset_id=DatasetId(value=model.linked_dataset_id)
        if model.linked_dataset_id
        else None,
        is_active=model.is_active,
        created_by=model.created_by,
        created_at=model.created_at,
    )


def apply_predictor_variable_to_model(
    entity: PredictorVariable, model: PredictorVariableModel
) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value if entity.tenant_id is not None else None
    model.name = entity.name
    model.code = entity.code
    model.category = entity.category.value
    model.variable_role = entity.variable_role.value
    model.data_type = entity.data_type.value
    model.unit = entity.unit
    model.value_min = entity.value_min
    model.value_max = entity.value_max
    model.is_required_for_mlr = entity.is_required_for_mlr
    model.linked_dataset_id = (
        entity.linked_dataset_id.value if entity.linked_dataset_id is not None else None
    )
    model.is_active = entity.is_active
    model.created_by = entity.created_by
    model.created_at = entity.created_at


def variable_selection_to_domain(model: VariableSelectionModel) -> VariableSelection:
    return VariableSelection(
        id=VariableSelectionId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        name=model.name,
        hazard_type=model.hazard_type,
        selected_variable_ids=tuple(
            PredictorVariableId.from_string(v) for v in model.selected_variable_ids
        ),
        status=VariableSelectionStatus(model.status),
        created_by=model.created_by,
        created_at=model.created_at,
    )


def apply_variable_selection_to_model(
    entity: VariableSelection, model: VariableSelectionModel
) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.name = entity.name
    model.hazard_type = entity.hazard_type
    model.selected_variable_ids = [str(v) for v in entity.selected_variable_ids]
    model.status = entity.status.value
    model.created_by = entity.created_by
    model.created_at = entity.created_at


def acquisition_job_to_domain(model: AcquisitionJobModel) -> AcquisitionJob:
    return AcquisitionJob(
        id=AcquisitionJobId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        provider=DataProvider(model.provider),
        source_reference=model.source_reference,
        format=AcquisitionFormat(model.format),
        dataset_source_id=DatasetSourceId(value=model.dataset_source_id),
        declared_crs=model.declared_crs,
        status=AcquisitionJobStatus(model.status),
        raw_content_base64=model.raw_content_base64,
        provenance=tuple(
            ProvenanceEntry(
                timestamp=datetime.fromisoformat(p["timestamp"]),
                actor=p["actor"],
                action=p["action"],
                description=p["description"],
                source_reference=p.get("source_reference"),
            )
            for p in model.provenance
        ),
        dataset_id=DatasetId(value=model.dataset_id) if model.dataset_id else None,
        error=model.error,
        requested_by=model.requested_by,
        scheduled_at=model.scheduled_at,
        started_at=model.started_at,
        completed_at=model.completed_at,
        remote_sensing_source=(
            RemoteSensingSource(model.remote_sensing_source)
            if model.remote_sensing_source
            else None
        ),
        aoi_id=str(model.aoi_id) if model.aoi_id else None,
        temporal_start=model.temporal_start,
        temporal_end=model.temporal_end,
        comparison_temporal_start=model.comparison_temporal_start,
        comparison_temporal_end=model.comparison_temporal_end,
        requested_preprocessing=tuple(
            PreprocessingStep(step) for step in model.requested_preprocessing
        ),
        requested_indices=tuple(SpectralIndex(index) for index in model.requested_indices),
        applied_preprocessing=tuple(
            PreprocessingStep(step) for step in model.applied_preprocessing
        ),
        extracted_features=model.extracted_features,
        skipped_features=model.skipped_features,
    )


def apply_acquisition_job_to_model(entity: AcquisitionJob, model: AcquisitionJobModel) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.provider = entity.provider.value
    model.source_reference = entity.source_reference
    model.format = entity.format.value
    model.dataset_source_id = entity.dataset_source_id.value
    model.declared_crs = entity.declared_crs
    model.status = entity.status.value
    model.raw_content_base64 = entity.raw_content_base64
    model.provenance = [
        {
            "timestamp": entry.timestamp.isoformat(),
            "actor": entry.actor,
            "action": entry.action,
            "description": entry.description,
            "source_reference": entry.source_reference,
        }
        for entry in entity.provenance
    ]
    model.dataset_id = entity.dataset_id.value if entity.dataset_id is not None else None
    model.error = entity.error
    model.requested_by = entity.requested_by
    model.scheduled_at = entity.scheduled_at
    model.started_at = entity.started_at
    model.completed_at = entity.completed_at
    model.remote_sensing_source = (
        entity.remote_sensing_source.value if entity.remote_sensing_source is not None else None
    )
    model.aoi_id = uuid_module.UUID(entity.aoi_id) if entity.aoi_id else None
    model.temporal_start = entity.temporal_start
    model.temporal_end = entity.temporal_end
    model.comparison_temporal_start = entity.comparison_temporal_start
    model.comparison_temporal_end = entity.comparison_temporal_end
    model.requested_preprocessing = [step.value for step in entity.requested_preprocessing]
    model.requested_indices = [index.value for index in entity.requested_indices]
    model.applied_preprocessing = [step.value for step in entity.applied_preprocessing]
    model.extracted_features = entity.extracted_features
    model.skipped_features = entity.skipped_features
