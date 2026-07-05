"""Commands for the Data Acquisition context. Plain dataclasses — no
behavior, just the data a handler needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, slots=True)
class RegisterDatasetSourceCommand:
    tenant_id: str | None
    name: str
    provider: str
    description: str
    issued_by: str


@dataclass(frozen=True, slots=True)
class CatalogDatasetCommand:
    tenant_id: str
    dataset_source_id: str
    name: str
    dataset_type: str
    source: str
    provider: str
    acquisition_date: date
    crs: str
    spatial_coverage: str
    temporal_coverage_start: str
    temporal_coverage_end: str
    processing_method: str
    spatial_resolution_m: float | None = None
    temporal_resolution: str | None = None
    model_used: str | None = None
    is_mlr_ready: bool = False
    is_correlation_ready: bool = False
    issued_by: str = ""


@dataclass(frozen=True, slots=True)
class ReviseDatasetCommand:
    tenant_id: str
    dataset_name: str
    dataset_type: str
    source: str
    provider: str
    acquisition_date: date
    crs: str
    spatial_coverage: str
    temporal_coverage_start: str
    temporal_coverage_end: str
    processing_method: str
    description: str
    spatial_resolution_m: float | None = None
    temporal_resolution: str | None = None
    model_used: str | None = None
    is_mlr_ready: bool = False
    is_correlation_ready: bool = False
    issued_by: str = ""


@dataclass(frozen=True, slots=True)
class RegisterPredictorVariableCommand:
    tenant_id: str | None
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
    issued_by: str = ""


@dataclass(frozen=True, slots=True)
class CreateVariableSelectionCommand:
    tenant_id: str
    name: str
    hazard_type: str | None
    selected_variable_ids: tuple[str, ...] = field(default_factory=tuple)
    issued_by: str = ""


@dataclass(frozen=True, slots=True)
class ConfirmVariableSelectionCommand:
    tenant_id: str
    variable_selection_id: str


@dataclass(frozen=True, slots=True)
class ScheduleAcquisitionJobCommand:
    tenant_id: str
    provider: str
    source_reference: str
    format: str
    dataset_source_id: str
    declared_crs: str
    raw_content_base64: str | None = None
    # --- Sprint 14: Remote Sensing Integration (GOOGLE_EARTH_ENGINE jobs only) ---
    remote_sensing_source: str | None = None
    aoi_id: str | None = None
    temporal_start: str | None = None
    temporal_end: str | None = None
    comparison_temporal_start: str | None = None
    comparison_temporal_end: str | None = None
    requested_preprocessing: tuple[str, ...] = field(default_factory=tuple)
    requested_indices: tuple[str, ...] = field(default_factory=tuple)
    issued_by: str = ""


@dataclass(frozen=True, slots=True)
class ExecuteAcquisitionJobCommand:
    tenant_id: str
    acquisition_job_id: str
    issued_by: str = ""
