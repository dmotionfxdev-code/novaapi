"""Query handlers — read-only, never mutate, never go through the
command pipeline (Application Layer §3/§4). Same pattern as every prior
context.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

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
    VariableSelectionNotFoundError,
)
from georisk.contexts.data_acquisition.domain.value_objects import (
    AcquisitionJobId,
    DatasetId,
    DatasetReadinessTag,
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


class ListDatasetSourcesQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId) -> list[DatasetSource]:
        return await SqlAlchemyDatasetSourceRepository(self._session).list_available(tenant_id)


class GetDatasetCatalogQuery:
    """The "Dataset Catalog" (requirement #1) read model, optionally
    filtered by type or by an MLR/correlation readiness tag (requirement
    #1's "Support: MLR-ready / Correlation-Analysis-ready datasets")."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self,
        tenant_id: TenantId,
        *,
        dataset_type: str | None = None,
        readiness: DatasetReadinessTag | None = None,
    ) -> list[Dataset]:
        return await SqlAlchemyDatasetRepository(self._session).list_catalog(
            tenant_id, dataset_type=dataset_type, readiness=readiness
        )


class GetDatasetQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, dataset_id: DatasetId) -> Dataset:
        dataset = await SqlAlchemyDatasetRepository(self._session).get_by_id(dataset_id)
        if dataset is None or str(dataset.tenant_id) != str(tenant_id):
            raise DatasetNotFoundError(f"Dataset {dataset_id} not found")
        return dataset


class ListDatasetVersionsQuery:
    """Also serves "Dataset Provenance Tracking" (requirement #3) — each
    version's own ``provenance`` tuple is visible on every returned
    ``Dataset``, so the full lineage is just "list every version"."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, name: str) -> list[Dataset]:
        return await SqlAlchemyDatasetRepository(self._session).list_versions(tenant_id, name)


class ListPredictorVariablesQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self, tenant_id: TenantId, *, category: str | None = None
    ) -> list[PredictorVariable]:
        return await SqlAlchemyPredictorVariableRepository(self._session).list_available(
            tenant_id, category=category
        )


class GetVariableSelectionQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self, tenant_id: TenantId, variable_selection_id: VariableSelectionId
    ) -> VariableSelection:
        selection = await SqlAlchemyVariableSelectionRepository(self._session).get_by_id(
            variable_selection_id
        )
        if selection is None or str(selection.tenant_id) != str(tenant_id):
            raise VariableSelectionNotFoundError(
                f"VariableSelection {variable_selection_id} not found"
            )
        return selection


class GetAcquisitionJobQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self, tenant_id: TenantId, acquisition_job_id: AcquisitionJobId
    ) -> AcquisitionJob:
        job = await SqlAlchemyAcquisitionJobRepository(self._session).get_by_id(
            acquisition_job_id
        )
        if job is None or str(job.tenant_id) != str(tenant_id):
            raise AcquisitionJobNotFoundError(f"AcquisitionJob {acquisition_job_id} not found")
        return job


class ListAcquisitionJobsQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId) -> list[AcquisitionJob]:
        return await SqlAlchemyAcquisitionJobRepository(self._session).list_by_tenant(tenant_id)
