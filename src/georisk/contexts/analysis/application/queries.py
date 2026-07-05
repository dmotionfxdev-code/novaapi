"""Query handlers — read-only, never mutate, never go through the command
pipeline (Application Layer §3/§4). Same pattern as every prior context.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.analysis.domain.entities import StageResult
from georisk.contexts.analysis.domain.errors import StageResultNotFoundError
from georisk.contexts.analysis.domain.value_objects import StageResultId, StageType
from georisk.contexts.analysis.infrastructure.repositories import SqlAlchemyStageResultRepository
from georisk.contexts.identity.domain.value_objects import TenantId


class GetStageResultQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, stage_result_id: StageResultId, tenant_id: TenantId) -> StageResult:
        result = await SqlAlchemyStageResultRepository(self._session).get_by_id(stage_result_id)
        if result is None or result.tenant_id != tenant_id:
            raise StageResultNotFoundError(f"StageResult {stage_result_id} not found")
        return result


class GetLatestStageResultQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self, tenant_id: TenantId, assessment_id: str, stage_type: StageType
    ) -> StageResult:
        result = await SqlAlchemyStageResultRepository(self._session).get_latest(
            tenant_id, assessment_id, stage_type
        )
        if result is None:
            raise StageResultNotFoundError(
                f"No completed StageResult for assessment {assessment_id} stage {stage_type}"
            )
        return result


class ListStageResultsQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, assessment_id: str) -> list[StageResult]:
        return await SqlAlchemyStageResultRepository(self._session).list_by_assessment(
            tenant_id, assessment_id
        )
