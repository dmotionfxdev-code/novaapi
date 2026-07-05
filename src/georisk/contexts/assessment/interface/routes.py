"""Assessment routes. Authentication/authorization is Identity's
``get_current_claims``/``require_permission`` dependencies — a legitimate
cross-context dependency under the shared-kernel relationship (Domain
Model §7; pyproject.toml's corrected import-linter contracts, Sprint 2),
not a violation of bounded-context independence. Every route is a thin
adapter: parse request -> build a command/query -> invoke the one
handler/query that owns it -> map the result to a response schema. No
business logic lives in this file.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.assessment.application.commands import (
    ArchiveAssessment,
    CancelAssessment,
    CreateAssessment,
    MarkAssessmentReady,
    ReportAssessment,
    StartAssessment,
    ValidateAssessment,
)
from georisk.contexts.assessment.application.handlers import (
    ArchiveAssessmentHandler,
    CancelAssessmentHandler,
    CreateAssessmentHandler,
    MarkAssessmentReadyHandler,
    ReportAssessmentHandler,
    StartAssessmentHandler,
    ValidateAssessmentHandler,
)
from georisk.contexts.assessment.application.queries import (
    GetAssessmentQuery,
    ListAssessmentsParams,
    ListAssessmentsQuery,
)
from georisk.contexts.assessment.application.workflow_engine import (
    StageExecutor,
    WorkflowEngine,
)
from georisk.contexts.assessment.application.workflow_queries import GetAssessmentWorkflowQuery
from georisk.contexts.assessment.domain.value_objects import (
    AssessmentId,
    AssessmentStatus,
    HazardType,
)
from georisk.contexts.assessment.domain.workflow_value_objects import StageType
from georisk.contexts.assessment.interface.schemas import (
    AssessmentListResponse,
    AssessmentResponse,
    CancelAssessmentRequest,
    CreateAssessmentRequest,
)
from georisk.contexts.assessment.interface.workflow_schemas import (
    AssessmentWorkflowResponse,
    StartWorkflowRequest,
)
from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.interface.dependencies import require_permission
from georisk.db.session import Database, get_database, get_session

router = APIRouter(prefix="/assessments", tags=["assessments"])


def get_stage_executor(request: Request) -> StageExecutor:
    """The concrete ``StageExecutor`` (Sprint 3's stub composed with any
    per-stage-type overrides, e.g. Validation's — Sprint 4) is constructed
    once, in ``api/app.py``'s lifespan, and stored on ``app.state``. This
    module only depends on the generic ``StageExecutor`` protocol it
    already owns (`application/workflow_engine.py`) — never on
    ``georisk.api.workflow_stage_executors`` or ``contexts.validation``
    directly, which would give ``contexts.assessment`` a transitive import
    path into another bounded context and violate the import-linter's
    peer-independence contract. Composing the concrete instance is the
    composition root's job (``api/app.py``), not this route module's.
    """
    return request.app.state.stage_executor


@router.post("", response_model=AssessmentResponse, status_code=201)
async def create_assessment(
    body: CreateAssessmentRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentResponse:
    handler = CreateAssessmentHandler(session)
    assessment = await handler.handle(
        CreateAssessment(
            tenant_id=str(claims.tenant_id),
            name=body.name,
            hazard_type=body.hazard_type,
            created_by=str(claims.user_id),
        )
    )
    return AssessmentResponse.from_domain(assessment)


@router.get("", response_model=AssessmentListResponse)
async def list_assessments(
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
    status: str | None = Query(default=None),
    hazard_type: str | None = Query(default=None),
) -> AssessmentListResponse:
    query = ListAssessmentsQuery(session)
    page = await query.handle(
        ListAssessmentsParams(
            tenant_id=claims.tenant_id,
            limit=limit,
            cursor=cursor,
            status=AssessmentStatus(status) if status else None,
            hazard_type=HazardType(hazard_type) if hazard_type else None,
        )
    )
    return AssessmentListResponse.from_page(page)


@router.get("/{assessment_id}", response_model=AssessmentResponse)
async def get_assessment(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentResponse:
    query = GetAssessmentQuery(session)
    assessment = await query.handle(AssessmentId.from_string(assessment_id), claims.tenant_id)
    return AssessmentResponse.from_domain(assessment)


@router.post("/{assessment_id}/actions/mark-ready", response_model=AssessmentResponse)
async def mark_assessment_ready(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentResponse:
    handler = MarkAssessmentReadyHandler(session)
    assessment = await handler.handle(
        MarkAssessmentReady(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            changed_by=str(claims.user_id),
        )
    )
    return AssessmentResponse.from_domain(assessment)


@router.post("/{assessment_id}/actions/start", response_model=AssessmentResponse)
async def start_assessment(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentResponse:
    handler = StartAssessmentHandler(session)
    assessment = await handler.handle(
        StartAssessment(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            changed_by=str(claims.user_id),
        )
    )
    return AssessmentResponse.from_domain(assessment)


@router.post("/{assessment_id}/actions/validate", response_model=AssessmentResponse)
async def validate_assessment(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentResponse:
    handler = ValidateAssessmentHandler(session)
    assessment = await handler.handle(
        ValidateAssessment(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            changed_by=str(claims.user_id),
        )
    )
    return AssessmentResponse.from_domain(assessment)


@router.post("/{assessment_id}/actions/report", response_model=AssessmentResponse)
async def report_assessment(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentResponse:
    handler = ReportAssessmentHandler(session)
    assessment = await handler.handle(
        ReportAssessment(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            changed_by=str(claims.user_id),
        )
    )
    return AssessmentResponse.from_domain(assessment)


@router.post("/{assessment_id}/actions/archive", response_model=AssessmentResponse)
async def archive_assessment(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_ARCHIVE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentResponse:
    handler = ArchiveAssessmentHandler(session)
    assessment = await handler.handle(
        ArchiveAssessment(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            archived_by=str(claims.user_id),
        )
    )
    return AssessmentResponse.from_domain(assessment)


@router.post("/{assessment_id}/actions/cancel", response_model=AssessmentResponse)
async def cancel_assessment(
    assessment_id: str,
    body: CancelAssessmentRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_CANCEL))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentResponse:
    handler = CancelAssessmentHandler(session)
    assessment = await handler.handle(
        CancelAssessment(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            reason=body.reason,
            cancelled_by=str(claims.user_id),
        )
    )
    return AssessmentResponse.from_domain(assessment)


# --- Workflow Engine (Roadmap Sprint 3) ------------------------------------
#
# These three routes need the whole `Database` (via `get_database`), not a
# single request-scoped `AsyncSession` — `WorkflowEngine` opens several of
# its own sequential transactions as it dispatches a cascade of stage
# commands (`workflow_engine.py`'s module docstring). `get_assessment_workflow`
# is a pure read and stays on the ordinary per-request session.


@router.post("/{assessment_id}/actions/start-workflow", response_model=AssessmentResponse)
async def start_workflow(
    assessment_id: str,
    body: StartWorkflowRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    db: Annotated[Database, Depends(get_database)],
    stage_executor: Annotated[StageExecutor, Depends(get_stage_executor)],
) -> AssessmentResponse:
    engine = WorkflowEngine(db, stage_executor)
    await engine.start_workflow(
        tenant_id=str(claims.tenant_id),
        assessment_id=assessment_id,
        workflow_template_id=body.workflow_template_id,
        actor=str(claims.user_id),
    )
    async with db.session() as session:
        assessment = await GetAssessmentQuery(session).handle(
            AssessmentId.from_string(assessment_id), claims.tenant_id
        )
    return AssessmentResponse.from_domain(assessment)


@router.post(
    "/{assessment_id}/stages/{stage_type}/actions/execute",
    response_model=AssessmentWorkflowResponse,
)
async def execute_stage_manually(
    assessment_id: str,
    stage_type: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    db: Annotated[Database, Depends(get_database)],
    stage_executor: Annotated[StageExecutor, Depends(get_stage_executor)],
) -> AssessmentWorkflowResponse:
    """Manual Stage Trigger Support (requirement #9) — a user directly runs
    a stage that's runnable but MANUAL-triggered (or retries a FAILED one),
    through the identical `WorkflowEngine.execute_stage` mechanism the
    engine itself uses for AUTOMATIC stages (requirement #10), just with a
    real user id as `actor` instead of `SYSTEM_ACTOR`.
    """
    engine = WorkflowEngine(db, stage_executor)
    await engine.execute_stage(
        tenant_id=str(claims.tenant_id),
        assessment_id=assessment_id,
        stage_type=StageType(stage_type),
        actor=str(claims.user_id),
    )
    async with db.session() as session:
        assessment = await GetAssessmentQuery(session).handle(
            AssessmentId.from_string(assessment_id), claims.tenant_id
        )
    return AssessmentWorkflowResponse.from_domain(assessment)


@router.get("/{assessment_id}/workflow", response_model=AssessmentWorkflowResponse)
async def get_assessment_workflow(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssessmentWorkflowResponse:
    assessment, _template = await GetAssessmentWorkflowQuery(session).handle(
        AssessmentId.from_string(assessment_id), claims.tenant_id
    )
    return AssessmentWorkflowResponse.from_domain(assessment)
