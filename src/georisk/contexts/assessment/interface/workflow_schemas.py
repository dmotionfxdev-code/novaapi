"""Pydantic request/response models for the Workflow API and Workflow Query
API — independent of the SQLAlchemy models and domain entities (Architecture
Redesign §9). Same pattern as ``schemas.py`` (Sprint 2).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.workflow_template import WorkflowTemplate


class StageDefinitionRequest(BaseModel):
    stage_type: str
    required_predecessors: list[str] = Field(default_factory=list)
    trigger_mode: str = "AUTOMATIC"
    max_attempts: int = Field(default=3, ge=1)


class CreateWorkflowTemplateRequest(BaseModel):
    hazard_type: str
    name: str = Field(min_length=1, max_length=200)
    stage_definitions: list[StageDefinitionRequest] = Field(min_length=1)


class StageDefinitionResponse(BaseModel):
    stage_type: str
    required_predecessors: list[str]
    trigger_mode: str
    max_attempts: int


class WorkflowTemplateResponse(BaseModel):
    id: str
    hazard_type: str
    name: str
    version: int
    status: str
    stage_definitions: list[StageDefinitionResponse]
    created_at: datetime

    @classmethod
    def from_domain(cls, template: WorkflowTemplate) -> WorkflowTemplateResponse:
        return cls(
            id=str(template.id),
            hazard_type=template.hazard_type.value,
            name=template.name,
            version=template.version,
            status=template.status.value,
            stage_definitions=[
                StageDefinitionResponse(
                    stage_type=sd.stage_type.value,
                    required_predecessors=sorted(p.value for p in sd.required_predecessors),
                    trigger_mode=sd.trigger_mode.value,
                    max_attempts=sd.max_attempts,
                )
                for sd in template.stage_definitions
            ],
            created_at=template.created_at,
        )


class StartWorkflowRequest(BaseModel):
    workflow_template_id: str


class StageProgressEntryResponse(BaseModel):
    stage_type: str
    status: str
    attempt_count: int
    stage_result_ref: str | None
    started_at: datetime | None
    completed_at: datetime | None
    last_error: str | None


class AssessmentWorkflowResponse(BaseModel):
    assessment_id: str
    workflow_template_id: str | None
    assessment_status: str
    entries: list[StageProgressEntryResponse]

    @classmethod
    def from_domain(cls, assessment: Assessment) -> AssessmentWorkflowResponse:
        return cls(
            assessment_id=str(assessment.id),
            workflow_template_id=assessment.workflow_template_id,
            assessment_status=assessment.status.value,
            entries=[
                StageProgressEntryResponse(
                    stage_type=e.stage_type.value,
                    status=e.status.value,
                    attempt_count=e.attempt_count,
                    stage_result_ref=e.stage_result_ref,
                    started_at=e.started_at,
                    completed_at=e.completed_at,
                    last_error=e.last_error,
                )
                for e in assessment.workflow_progress.entries
            ],
        )
