"""StageResult read API — nested under
``/assessments/{assessment_id}/stage-results`` purely as a URL-path
convenience; this router never imports anything from
``contexts.assessment`` (``assessment_id`` is handled as an opaque path
string throughout, exactly like Validation's router in Sprint 4).
Read-only: a ``StageResult`` is produced only by the Workflow-Engine
-triggered ``RecordStageResultCommand`` pipeline (composition root), never
via this API. Permission reuses ``assessment:view`` — a ``StageResult`` is
read-only evidence about an assessment a caller can already see.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.analysis.application.queries import (
    GetLatestStageResultQuery,
    ListStageResultsQuery,
)
from georisk.contexts.analysis.domain.errors import StageResultNotFoundError
from georisk.contexts.analysis.domain.value_objects import StageType
from georisk.contexts.analysis.interface.schemas import StageResultListResponse, StageResultResponse
from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.interface.dependencies import require_permission
from georisk.db.session import get_session

router = APIRouter(prefix="/assessments/{assessment_id}/stage-results", tags=["stage-results"])


@router.get("", response_model=StageResultListResponse)
async def list_stage_results(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StageResultListResponse:
    query = ListStageResultsQuery(session)
    results = await query.handle(claims.tenant_id, assessment_id)
    return StageResultListResponse.from_domain(results)


@router.get("/{stage_type}", response_model=StageResultResponse)
async def get_latest_stage_result(
    assessment_id: str,
    stage_type: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StageResultResponse:
    query = GetLatestStageResultQuery(session)
    try:
        result = await query.handle(claims.tenant_id, assessment_id, StageType(stage_type))
    except ValueError as exc:
        raise StageResultNotFoundError(f"Unknown stage type {stage_type!r}") from exc
    return StageResultResponse.from_domain(result)
