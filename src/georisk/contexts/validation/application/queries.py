"""Query handlers — read-only, never mutate, never go through the command
pipeline (Application Layer §3/§4). Same pattern as every prior context.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.validation.domain.entities import ValidationRun
from georisk.contexts.validation.domain.errors import ValidationRunNotFoundError
from georisk.contexts.validation.domain.value_objects import ValidationRunId
from georisk.contexts.validation.infrastructure.repositories import (
    SqlAlchemyValidationRunRepository,
)
from georisk.shared_kernel.types import CursorPage


class GetValidationRunQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self, validation_run_id: ValidationRunId, tenant_id: TenantId
    ) -> ValidationRun:
        run = await SqlAlchemyValidationRunRepository(self._session).get_by_id(validation_run_id)
        if run is None or run.tenant_id != tenant_id:
            # Same "don't leak existence across tenants" discipline as
            # every prior context's query handlers.
            raise ValidationRunNotFoundError(f"ValidationRun {validation_run_id} not found")
        return run


@dataclass(frozen=True, slots=True)
class ListValidationRunsParams:
    tenant_id: TenantId
    assessment_id: str
    limit: int = 25
    cursor: str | None = None


class ListValidationRunsQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, params: ListValidationRunsParams) -> CursorPage[ValidationRun]:
        limit = min(max(params.limit, 1), 100)
        runs, next_cursor, has_more = await SqlAlchemyValidationRunRepository(
            self._session
        ).list_by_assessment(
            params.tenant_id, params.assessment_id, limit=limit, cursor=params.cursor
        )
        return CursorPage(items=runs, next_cursor=next_cursor, has_more=has_more)
