"""Query handlers — read-only, never mutate, never go through the command
pipeline (Application Layer §3/§4). Same pattern as Identity, Sprint 1.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.errors import AssessmentNotFoundError
from georisk.contexts.assessment.domain.value_objects import (
    AssessmentId,
    AssessmentStatus,
    HazardType,
)
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.shared_kernel.types import CursorPage


class GetAssessmentQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, assessment_id: AssessmentId, tenant_id: TenantId) -> Assessment:
        assessment = await SqlAlchemyAssessmentRepository(self._session).get_by_id(assessment_id)
        if assessment is None or assessment.tenant_id != tenant_id:
            # Same "don't leak existence across tenants" discipline as the
            # command handlers (handlers.py's _assert_same_tenant).
            raise AssessmentNotFoundError(f"Assessment {assessment_id} not found")
        return assessment


@dataclass(frozen=True, slots=True)
class ListAssessmentsParams:
    tenant_id: TenantId
    limit: int = 25
    cursor: str | None = None
    status: AssessmentStatus | None = None
    hazard_type: HazardType | None = None


class ListAssessmentsQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, params: ListAssessmentsParams) -> CursorPage[Assessment]:
        limit = min(max(params.limit, 1), 100)
        assessments, next_cursor, has_more = await SqlAlchemyAssessmentRepository(
            self._session
        ).list_by_tenant(
            params.tenant_id,
            limit=limit,
            cursor=params.cursor,
            status=params.status,
            hazard_type=params.hazard_type,
        )
        return CursorPage(items=assessments, next_cursor=next_cursor, has_more=has_more)
