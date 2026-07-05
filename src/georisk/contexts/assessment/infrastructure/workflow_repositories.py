"""Concrete SQLAlchemy repository implementing
``contexts/assessment/domain/workflow_repositories.WorkflowTemplateRepository``.
No optimistic-concurrency version column — templates are authored by one
platform admin at a time (Platform Architecture §5), unlike ``Assessment``,
which is genuinely subject to concurrent tenant-side commands. Adding a
version column here with no code path that could ever race it would be
speculative, not "production-ready" (coding standard: no guard for a
scenario that can't happen).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.assessment.domain.value_objects import HazardType
from georisk.contexts.assessment.domain.workflow_template import (
    WorkflowTemplate,
    WorkflowTemplateId,
)
from georisk.contexts.assessment.domain.workflow_value_objects import WorkflowTemplateStatus
from georisk.contexts.assessment.infrastructure import mappers
from georisk.contexts.assessment.infrastructure.models import WorkflowTemplateModel


class SqlAlchemyWorkflowTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, template_id: WorkflowTemplateId) -> WorkflowTemplate | None:
        model = await self._session.get(WorkflowTemplateModel, template_id.value)
        return mappers.workflow_template_to_domain(model) if model else None

    async def list_all(self) -> list[WorkflowTemplate]:
        result = await self._session.execute(
            select(WorkflowTemplateModel).order_by(WorkflowTemplateModel.created_at)
        )
        return [mappers.workflow_template_to_domain(m) for m in result.scalars().all()]

    async def list_published_for_hazard_type(
        self, hazard_type: HazardType
    ) -> list[WorkflowTemplate]:
        query = select(WorkflowTemplateModel).where(
            WorkflowTemplateModel.hazard_type == hazard_type.value,
            WorkflowTemplateModel.status == WorkflowTemplateStatus.PUBLISHED.value,
        )
        result = await self._session.execute(query)
        return [mappers.workflow_template_to_domain(m) for m in result.scalars().all()]

    async def save(self, template: WorkflowTemplate) -> None:
        model = await self._session.get(WorkflowTemplateModel, template.id.value)
        if model is None:
            model = WorkflowTemplateModel()
            mappers.apply_workflow_template_to_model(template, model)
            self._session.add(model)
            return
        mappers.apply_workflow_template_to_model(template, model)
