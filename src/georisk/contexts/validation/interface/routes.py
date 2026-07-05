"""Validation API (API Resource Model §18) — nested under
``/assessments/{assessment_id}/validations`` purely as a URL-path
convenience for clients; this router never imports anything from
``contexts.assessment`` (``assessment_id`` is handled as an opaque path
string throughout, exactly like ``subject_id``), so path nesting here
creates no context coupling. Every route is a thin adapter: parse request
-> build a command/query -> invoke the one handler/query that owns it ->
map to a response schema — no business logic in this file.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.interface.dependencies import require_permission
from georisk.contexts.validation.application.commands import (
    RunRegressionValidationCommand,
    RunValidationCommand,
)
from georisk.contexts.validation.application.handlers import (
    RunRegressionValidationHandler,
    RunValidationHandler,
)
from georisk.contexts.validation.application.ports import (
    RegressionValidationSubjectResolver,
    StubValidationSubjectResolver,
)
from georisk.contexts.validation.application.queries import (
    GetValidationRunQuery,
    ListValidationRunsParams,
    ListValidationRunsQuery,
)
from georisk.contexts.validation.domain.errors import ValidationRunNotFoundError
from georisk.contexts.validation.domain.value_objects import ValidationRunId
from georisk.contexts.validation.interface.schemas import (
    RunRegressionValidationRequest,
    RunValidationRequest,
    ValidationRunListResponse,
    ValidationRunResponse,
)
from georisk.db.session import get_session

router = APIRouter(prefix="/assessments/{assessment_id}/validations", tags=["validation"])


def get_regression_validation_subject_resolver(
    request: Request,
) -> RegressionValidationSubjectResolver:
    """Reads the composition-root instance off ``request.app.state``
    (constructed in ``api/app.py``'s lifespan from ``api/
    validation_ports.py``) — never imports the concrete composition-root
    class directly, which would give ``contexts.validation`` a transitive
    import path into ``contexts.prediction`` and violate the
    import-linter's peer-independence contract. Same reasoning as
    ``contexts/prediction/interface/routes.py``'s
    ``get_variable_selection_reader`` docstring.
    """
    return request.app.state.regression_validation_subject_resolver


@router.get("", response_model=ValidationRunListResponse)
async def list_validation_runs(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.VALIDATION_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> ValidationRunListResponse:
    query = ListValidationRunsQuery(session)
    page = await query.handle(
        ListValidationRunsParams(
            tenant_id=claims.tenant_id, assessment_id=assessment_id, limit=limit, cursor=cursor
        )
    )
    return ValidationRunListResponse.from_page(page)


@router.get("/{validation_run_id}", response_model=ValidationRunResponse)
async def get_validation_run(
    assessment_id: str,
    validation_run_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.VALIDATION_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ValidationRunResponse:
    query = GetValidationRunQuery(session)
    run = await query.handle(ValidationRunId.from_string(validation_run_id), claims.tenant_id)
    if run.assessment_id != assessment_id:
        # Same "don't leak existence across a boundary" discipline as
        # cross-tenant checks elsewhere — here scoped to the assessment
        # nesting in the URL rather than the tenant.
        raise ValidationRunNotFoundError(f"ValidationRun {validation_run_id} not found")
    return ValidationRunResponse.from_domain(run)


@router.post("/actions/run", response_model=ValidationRunResponse, status_code=201)
async def run_validation(
    assessment_id: str,
    body: RunValidationRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.VALIDATION_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ValidationRunResponse:
    """Ad hoc re-validation (API Resource Model §18) — issued by a real
    user, distinguishable from the Workflow-Engine-triggered run only by
    ``issuedBy`` in the response, exactly as designed.
    """
    handler = RunValidationHandler(session, StubValidationSubjectResolver())
    run = await handler.handle(
        RunValidationCommand(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            subject_id=body.subject_id,
            subject_type=body.subject_type,
            issued_by=str(claims.user_id),
        )
    )
    return ValidationRunResponse.from_domain(run)


@router.post("/actions/run-regression", response_model=ValidationRunResponse, status_code=201)
async def run_regression_validation(
    assessment_id: str,
    body: RunRegressionValidationRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.VALIDATION_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
    resolver: Annotated[
        RegressionValidationSubjectResolver, Depends(get_regression_validation_subject_resolver)
    ],
) -> ValidationRunResponse:
    """Sprint 10 requirement #4 — "Integrate with Prediction Context":
    ``body.subject_id`` is a real ``PredictionRunId``; the injected
    resolver reads that ``PredictionRun``'s already-computed regression
    fit statistics directly (see ``api/validation_ports.py``)."""
    handler = RunRegressionValidationHandler(session, resolver)
    run = await handler.handle(
        RunRegressionValidationCommand(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            subject_id=body.subject_id,
            issued_by=str(claims.user_id),
        )
    )
    return ValidationRunResponse.from_domain(run)
