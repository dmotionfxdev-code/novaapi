"""Repository interface for the ``WorkflowTemplate`` aggregate — same
coarse-grained get/save contract as ``repositories.AssessmentRepository``.
Concrete SQLAlchemy implementation lives in
``infrastructure/workflow_repositories.py``.
"""

from __future__ import annotations

from typing import Protocol

from georisk.contexts.assessment.domain.value_objects import HazardType
from georisk.contexts.assessment.domain.workflow_template import (
    WorkflowTemplate,
    WorkflowTemplateId,
)


class WorkflowTemplateRepository(Protocol):
    async def get_by_id(self, template_id: WorkflowTemplateId) -> WorkflowTemplate | None: ...

    async def list_all(self) -> list[WorkflowTemplate]: ...

    async def list_published_for_hazard_type(
        self, hazard_type: HazardType
    ) -> list[WorkflowTemplate]: ...

    async def save(self, template: WorkflowTemplate) -> None: ...
