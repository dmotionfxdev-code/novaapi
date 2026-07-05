"""Query handlers for WorkflowTemplate and Assessment-workflow-progress
reads — read-only, never mutate, never go through the command pipeline
(Application Layer §3/§4). Same pattern as ``queries.py`` (Sprint 2).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.errors import (
    AssessmentNotFoundError,
    WorkflowTemplateNotFoundError,
)
from georisk.contexts.assessment.domain.value_objects import AssessmentId
from georisk.contexts.assessment.domain.workflow_template import (
    WorkflowTemplate,
    WorkflowTemplateId,
)
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.assessment.infrastructure.workflow_repositories import (
    SqlAlchemyWorkflowTemplateRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId


class GetWorkflowTemplateQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, template_id: WorkflowTemplateId) -> WorkflowTemplate:
        template = await SqlAlchemyWorkflowTemplateRepository(self._session).get_by_id(template_id)
        if template is None:
            raise WorkflowTemplateNotFoundError(f"WorkflowTemplate {template_id} not found")
        return template


class ListWorkflowTemplatesQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self) -> list[WorkflowTemplate]:
        return await SqlAlchemyWorkflowTemplateRepository(self._session).list_all()


class GetAssessmentWorkflowQuery:
    """Backs the "Workflow Query API" requirement — returns the assessment
    together with its currently-bound (if any) ``WorkflowTemplate``, so the
    interface layer can render each ``StageProgressEntry`` alongside the
    template's declared DAG (predecessors, trigger mode) without a second
    round trip from the caller.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self, assessment_id: AssessmentId, tenant_id: TenantId
    ) -> tuple[Assessment, WorkflowTemplate | None]:
        assessment = await SqlAlchemyAssessmentRepository(self._session).get_by_id(assessment_id)
        if assessment is None or assessment.tenant_id != tenant_id:
            raise AssessmentNotFoundError(f"Assessment {assessment_id} not found")
        template = None
        if assessment.workflow_template_id:
            template = await SqlAlchemyWorkflowTemplateRepository(self._session).get_by_id(
                WorkflowTemplateId.from_string(assessment.workflow_template_id)
            )
        return assessment, template
