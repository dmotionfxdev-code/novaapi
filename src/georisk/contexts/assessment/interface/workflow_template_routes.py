"""WorkflowTemplate authoring/catalog routes — the "Workflow Template
Aggregate" requirement's API surface. Every route is a thin adapter: parse
request -> build a command/query -> invoke the one handler/query that owns
it -> map to a response schema, same discipline as
``interface/routes.py`` (Sprint 2).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.assessment.application.workflow_commands import (
    CreateWorkflowTemplateCommand,
    PublishWorkflowTemplateCommand,
)
from georisk.contexts.assessment.application.workflow_handlers import (
    CreateWorkflowTemplateHandler,
    PublishWorkflowTemplateHandler,
)
from georisk.contexts.assessment.application.workflow_queries import (
    GetWorkflowTemplateQuery,
    ListWorkflowTemplatesQuery,
)
from georisk.contexts.assessment.domain.workflow_template import WorkflowTemplateId
from georisk.contexts.assessment.interface.workflow_schemas import (
    CreateWorkflowTemplateRequest,
    WorkflowTemplateResponse,
)
from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.interface.dependencies import require_permission
from georisk.db.session import get_session

router = APIRouter(prefix="/workflow-templates", tags=["workflow-templates"])


@router.post("", response_model=WorkflowTemplateResponse, status_code=201)
async def create_workflow_template(
    body: CreateWorkflowTemplateRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.WORKFLOW_TEMPLATE_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowTemplateResponse:
    handler = CreateWorkflowTemplateHandler(session)
    template = await handler.handle(
        CreateWorkflowTemplateCommand(
            hazard_type=body.hazard_type,
            name=body.name,
            stage_definitions=[sd.model_dump() for sd in body.stage_definitions],
        )
    )
    return WorkflowTemplateResponse.from_domain(template)


@router.post("/{template_id}/actions/publish", response_model=WorkflowTemplateResponse)
async def publish_workflow_template(
    template_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.WORKFLOW_TEMPLATE_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowTemplateResponse:
    handler = PublishWorkflowTemplateHandler(session)
    template = await handler.handle(
        PublishWorkflowTemplateCommand(workflow_template_id=template_id)
    )
    return WorkflowTemplateResponse.from_domain(template)


@router.get("", response_model=list[WorkflowTemplateResponse])
async def list_workflow_templates(
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.WORKFLOW_TEMPLATE_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[WorkflowTemplateResponse]:
    query = ListWorkflowTemplatesQuery(session)
    templates = await query.handle()
    return [WorkflowTemplateResponse.from_domain(t) for t in templates]


@router.get("/{template_id}", response_model=WorkflowTemplateResponse)
async def get_workflow_template(
    template_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.WORKFLOW_TEMPLATE_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WorkflowTemplateResponse:
    query = GetWorkflowTemplateQuery(session)
    template = await query.handle(WorkflowTemplateId.from_string(template_id))
    return WorkflowTemplateResponse.from_domain(template)
