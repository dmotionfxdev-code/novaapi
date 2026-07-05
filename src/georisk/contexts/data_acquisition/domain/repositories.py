"""Repository interfaces — domain layer contracts (Application Layer §1:
one repository per aggregate root). Concrete SQLAlchemy implementations
live in ``contexts/data_acquisition/infrastructure/repositories.py``.
"""

from __future__ import annotations

from typing import Protocol

from georisk.contexts.data_acquisition.domain.entities import (
    AcquisitionJob,
    Dataset,
    DatasetSource,
    PredictorVariable,
    VariableSelection,
)
from georisk.contexts.data_acquisition.domain.value_objects import (
    AcquisitionJobId,
    DatasetId,
    DatasetReadinessTag,
    DatasetSourceId,
    PredictorVariableId,
    VariableSelectionId,
)
from georisk.contexts.identity.domain.value_objects import TenantId


class DatasetSourceRepository(Protocol):
    async def get_by_id(self, dataset_source_id: DatasetSourceId) -> DatasetSource | None: ...

    async def list_available(self, tenant_id: TenantId) -> list[DatasetSource]:
        """Every global (``tenant_id=None``) source plus this tenant's
        own private sources."""
        ...

    async def save(self, source: DatasetSource) -> None: ...


class DatasetRepository(Protocol):
    async def get_by_id(self, dataset_id: DatasetId) -> Dataset | None: ...

    async def get_latest(self, tenant_id: TenantId, name: str) -> Dataset | None: ...

    async def list_versions(self, tenant_id: TenantId, name: str) -> list[Dataset]: ...

    async def list_catalog(
        self,
        tenant_id: TenantId,
        *,
        dataset_type: str | None = None,
        readiness: DatasetReadinessTag | None = None,
    ) -> list[Dataset]:
        """The "Dataset Catalog" (requirement #1) read model — every
        current (non-superseded) dataset, optionally filtered by type or
        by an MLR/correlation readiness tag."""
        ...

    async def save(self, dataset: Dataset) -> None: ...


class PredictorVariableRepository(Protocol):
    async def get_by_id(
        self, predictor_variable_id: PredictorVariableId
    ) -> PredictorVariable | None: ...

    async def list_available(
        self, tenant_id: TenantId, *, category: str | None = None
    ) -> list[PredictorVariable]: ...

    async def save(self, variable: PredictorVariable) -> None: ...


class VariableSelectionRepository(Protocol):
    async def get_by_id(
        self, variable_selection_id: VariableSelectionId
    ) -> VariableSelection | None: ...

    async def save(self, selection: VariableSelection) -> None: ...


class AcquisitionJobRepository(Protocol):
    async def get_by_id(self, acquisition_job_id: AcquisitionJobId) -> AcquisitionJob | None: ...

    async def list_by_tenant(self, tenant_id: TenantId) -> list[AcquisitionJob]: ...

    async def save(self, job: AcquisitionJob) -> None: ...
