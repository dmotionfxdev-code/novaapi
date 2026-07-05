"""Query handlers — read-only, never mutate, never go through the
command pipeline (Application Layer §3/§4). Same pattern as every prior
context.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.prediction.domain.entities import PredictionRun
from georisk.contexts.prediction.domain.errors import PredictionRunNotFoundError
from georisk.contexts.prediction.domain.value_objects import PredictionRunId
from georisk.contexts.prediction.infrastructure.repositories import (
    SqlAlchemyPredictionRunRepository,
)


class GetPredictionRunQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self, tenant_id: TenantId, prediction_run_id: PredictionRunId
    ) -> PredictionRun:
        run = await SqlAlchemyPredictionRunRepository(self._session).get_by_id(prediction_run_id)
        if run is None or run.tenant_id != tenant_id:
            raise PredictionRunNotFoundError(f"PredictionRun {prediction_run_id} not found")
        return run


class ListPredictionRunsQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, assessment_id: str) -> list[PredictionRun]:
        return await SqlAlchemyPredictionRunRepository(self._session).list_by_assessment(
            tenant_id, assessment_id
        )
