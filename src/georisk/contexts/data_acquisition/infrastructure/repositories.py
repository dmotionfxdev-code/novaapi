"""Concrete SQLAlchemy repositories implementing
``contexts/data_acquisition/domain/repositories.py``'s Protocols.
``Dataset`` is write-once-per-version (Domain Model precedent:
``StageResult``/``AreaOfInterest``) — ``save`` always inserts a new row
for a new ``Dataset`` instance; ``DatasetSource``/``PredictorVariable``/
``VariableSelection`` are simple mutable single-row aggregates.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    DatasetStatus,
    PredictorVariableId,
    VariableSelectionId,
)
from georisk.contexts.data_acquisition.infrastructure import mappers
from georisk.contexts.data_acquisition.infrastructure.models import (
    AcquisitionJobModel,
    DatasetModel,
    DatasetSourceModel,
    PredictorVariableModel,
    VariableSelectionModel,
)
from georisk.contexts.identity.domain.value_objects import TenantId


class SqlAlchemyDatasetSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, dataset_source_id: DatasetSourceId) -> DatasetSource | None:
        model = await self._session.get(DatasetSourceModel, dataset_source_id.value)
        return mappers.dataset_source_to_domain(model) if model else None

    async def list_available(self, tenant_id: TenantId) -> list[DatasetSource]:
        query = (
            select(DatasetSourceModel)
            .where(
                or_(
                    DatasetSourceModel.tenant_id == tenant_id.value,
                    DatasetSourceModel.tenant_id.is_(None),
                ),
                DatasetSourceModel.is_active.is_(True),
            )
            .order_by(DatasetSourceModel.name)
        )
        result = await self._session.execute(query)
        return [mappers.dataset_source_to_domain(m) for m in result.scalars().all()]

    async def save(self, source: DatasetSource) -> None:
        model = await self._session.get(DatasetSourceModel, source.id.value)
        if model is None:
            model = DatasetSourceModel()
            self._session.add(model)
        mappers.apply_dataset_source_to_model(source, model)


class SqlAlchemyDatasetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, dataset_id: DatasetId) -> Dataset | None:
        model = await self._session.get(DatasetModel, dataset_id.value)
        return mappers.dataset_to_domain(model) if model else None

    async def get_latest(self, tenant_id: TenantId, name: str) -> Dataset | None:
        query = (
            select(DatasetModel)
            .where(
                DatasetModel.tenant_id == tenant_id.value,
                DatasetModel.metadata_name == name,
                DatasetModel.status == DatasetStatus.CATALOGUED.value,
            )
            .order_by(DatasetModel.version.desc())
            .limit(1)
        )
        result = await self._session.execute(query)
        model = result.scalar_one_or_none()
        return mappers.dataset_to_domain(model) if model else None

    async def list_versions(self, tenant_id: TenantId, name: str) -> list[Dataset]:
        query = (
            select(DatasetModel)
            .where(DatasetModel.tenant_id == tenant_id.value, DatasetModel.metadata_name == name)
            .order_by(DatasetModel.version)
        )
        result = await self._session.execute(query)
        return [mappers.dataset_to_domain(m) for m in result.scalars().all()]

    async def list_catalog(
        self,
        tenant_id: TenantId,
        *,
        dataset_type: str | None = None,
        readiness: DatasetReadinessTag | None = None,
    ) -> list[Dataset]:
        query = select(DatasetModel).where(
            DatasetModel.tenant_id == tenant_id.value,
            DatasetModel.status == DatasetStatus.CATALOGUED.value,
        )
        if dataset_type is not None:
            query = query.where(DatasetModel.dataset_type == dataset_type)
        query = query.order_by(DatasetModel.metadata_name)
        result = await self._session.execute(query)
        datasets = [mappers.dataset_to_domain(m) for m in result.scalars().all()]
        if readiness is not None:
            datasets = [d for d in datasets if readiness in d.readiness]
        return datasets

    async def save(self, dataset: Dataset) -> None:
        model = await self._session.get(DatasetModel, dataset.id.value)
        if model is None:
            model = DatasetModel()
            self._session.add(model)
        mappers.apply_dataset_to_model(dataset, model)


class SqlAlchemyPredictorVariableRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, predictor_variable_id: PredictorVariableId
    ) -> PredictorVariable | None:
        model = await self._session.get(PredictorVariableModel, predictor_variable_id.value)
        return mappers.predictor_variable_to_domain(model) if model else None

    async def list_available(
        self, tenant_id: TenantId, *, category: str | None = None
    ) -> list[PredictorVariable]:
        query = select(PredictorVariableModel).where(
            or_(
                PredictorVariableModel.tenant_id == tenant_id.value,
                PredictorVariableModel.tenant_id.is_(None),
            ),
            PredictorVariableModel.is_active.is_(True),
        )
        if category is not None:
            query = query.where(PredictorVariableModel.category == category)
        query = query.order_by(PredictorVariableModel.category, PredictorVariableModel.name)
        result = await self._session.execute(query)
        return [mappers.predictor_variable_to_domain(m) for m in result.scalars().all()]

    async def save(self, variable: PredictorVariable) -> None:
        model = await self._session.get(PredictorVariableModel, variable.id.value)
        if model is None:
            model = PredictorVariableModel()
            self._session.add(model)
        mappers.apply_predictor_variable_to_model(variable, model)


class SqlAlchemyVariableSelectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(
        self, variable_selection_id: VariableSelectionId
    ) -> VariableSelection | None:
        model = await self._session.get(VariableSelectionModel, variable_selection_id.value)
        return mappers.variable_selection_to_domain(model) if model else None

    async def save(self, selection: VariableSelection) -> None:
        model = await self._session.get(VariableSelectionModel, selection.id.value)
        if model is None:
            model = VariableSelectionModel()
            self._session.add(model)
        mappers.apply_variable_selection_to_model(selection, model)


class SqlAlchemyAcquisitionJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, acquisition_job_id: AcquisitionJobId) -> AcquisitionJob | None:
        model = await self._session.get(AcquisitionJobModel, acquisition_job_id.value)
        return mappers.acquisition_job_to_domain(model) if model else None

    async def list_by_tenant(self, tenant_id: TenantId) -> list[AcquisitionJob]:
        query = (
            select(AcquisitionJobModel)
            .where(AcquisitionJobModel.tenant_id == tenant_id.value)
            .order_by(AcquisitionJobModel.scheduled_at.desc())
        )
        result = await self._session.execute(query)
        return [mappers.acquisition_job_to_domain(m) for m in result.scalars().all()]

    async def save(self, job: AcquisitionJob) -> None:
        model = await self._session.get(AcquisitionJobModel, job.id.value)
        if model is None:
            model = AcquisitionJobModel()
            self._session.add(model)
        mappers.apply_acquisition_job_to_model(job, model)
