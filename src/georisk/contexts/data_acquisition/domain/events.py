"""Data Acquisition domain events — appended to the outbox within the
same transaction as the aggregate they describe (matching every prior
context's pattern).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class DatasetSourceRegistered:
    event_type: ClassVar[str] = "data_acquisition.DatasetSourceRegistered"
    dataset_source_id: str
    tenant_id: str | None
    name: str
    provider: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class DatasetCatalogued:
    event_type: ClassVar[str] = "data_acquisition.DatasetCatalogued"
    dataset_id: str
    tenant_id: str
    name: str
    version: int

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class DatasetRevised:
    event_type: ClassVar[str] = "data_acquisition.DatasetRevised"
    dataset_id: str
    tenant_id: str
    version: int
    superseded_dataset_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class PredictorVariableRegistered:
    event_type: ClassVar[str] = "data_acquisition.PredictorVariableRegistered"
    predictor_variable_id: str
    tenant_id: str | None
    name: str
    category: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class VariableSelectionCreated:
    event_type: ClassVar[str] = "data_acquisition.VariableSelectionCreated"
    variable_selection_id: str
    tenant_id: str
    name: str
    variable_count: int

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class VariableSelectionConfirmed:
    event_type: ClassVar[str] = "data_acquisition.VariableSelectionConfirmed"
    variable_selection_id: str
    tenant_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class AcquisitionJobScheduled:
    event_type: ClassVar[str] = "data_acquisition.AcquisitionJobScheduled"
    acquisition_job_id: str
    tenant_id: str
    provider: str
    format: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class AcquisitionJobStarted:
    event_type: ClassVar[str] = "data_acquisition.AcquisitionJobStarted"
    acquisition_job_id: str
    tenant_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class AcquisitionJobCompleted:
    event_type: ClassVar[str] = "data_acquisition.AcquisitionJobCompleted"
    acquisition_job_id: str
    tenant_id: str
    dataset_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class AcquisitionJobFailed:
    event_type: ClassVar[str] = "data_acquisition.AcquisitionJobFailed"
    acquisition_job_id: str
    tenant_id: str
    error: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}
