"""Concrete SQLAlchemy repository implementing
``contexts/prediction/domain/repositories.PredictionRunRepository``.
Write-once per version — ``save`` always inserts a new row (Sprint 8
requirement #7 — Versioning, matching ``StageResult``'s exact
"immutable, write-once-per-version" precedent).
"""

from __future__ import annotations

import uuid as uuid_module

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.prediction.domain.entities import PredictionRun
from georisk.contexts.prediction.domain.value_objects import PredictionMethod, PredictionRunId
from georisk.contexts.prediction.infrastructure import mappers
from georisk.contexts.prediction.infrastructure.models import PredictionRunModel


class SqlAlchemyPredictionRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, prediction_run_id: PredictionRunId) -> PredictionRun | None:
        model = await self._session.get(PredictionRunModel, prediction_run_id.value)
        return mappers.prediction_run_to_domain(model) if model else None

    async def list_by_assessment(
        self, tenant_id: TenantId, assessment_id: str
    ) -> list[PredictionRun]:
        query = (
            select(PredictionRunModel)
            .where(
                PredictionRunModel.tenant_id == tenant_id.value,
                PredictionRunModel.assessment_id == uuid_module.UUID(assessment_id),
            )
            .order_by(PredictionRunModel.created_at.desc())
        )
        result = await self._session.execute(query)
        return [mappers.prediction_run_to_domain(m) for m in result.scalars().all()]

    async def next_version(
        self,
        tenant_id: TenantId,
        assessment_id: str,
        variable_selection_id: str,
        method: PredictionMethod,
    ) -> int:
        query = select(func.coalesce(func.max(PredictionRunModel.version), 0) + 1).where(
            PredictionRunModel.tenant_id == tenant_id.value,
            PredictionRunModel.assessment_id == uuid_module.UUID(assessment_id),
            PredictionRunModel.variable_selection_id == uuid_module.UUID(variable_selection_id),
            PredictionRunModel.method == method.value,
        )
        result = await self._session.scalar(query)
        assert result is not None  # coalesce(..., 0) + 1 always yields a value
        return result

    async def save(self, run: PredictionRun) -> None:
        model = PredictionRunModel()
        mappers.apply_prediction_run_to_model(run, model)
        self._session.add(model)
