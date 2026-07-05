"""Command DTOs for the Workflow Engine (Roadmap Sprint 3). The four names
required by the sprint brief — ``StartWorkflowCommand``, ``ExecuteStageCommand``,
``RecordStageCompletionCommand``, ``AdvanceAssessmentCommand`` — are used
verbatim, unlike Sprint 2's un-suffixed command names (``CreateAssessment``,
etc.), since the brief names them literally. ``RecordStageFailureCommand``
and the two ``WorkflowTemplate`` authoring commands are this sprint's own
additions, named consistently with that same "Command" suffix.

Every command here still follows Application Layer §9: one command, one
handler, one aggregate instance touched per transaction. Multi-step
orchestration (dispatch the next wave of stages, retry, advance once
everything's done) is the ``WorkflowEngine`` application service's job
(``workflow_engine.py``) — it issues these commands one at a time through
their own handlers, never batches several aggregate changes into one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CreateWorkflowTemplateCommand:
    hazard_type: str
    name: str
    stage_definitions: list[dict]


@dataclass(frozen=True, slots=True)
class PublishWorkflowTemplateCommand:
    workflow_template_id: str


@dataclass(frozen=True, slots=True)
class StartWorkflowCommand:
    tenant_id: str
    assessment_id: str
    workflow_template_id: str
    actor: str


@dataclass(frozen=True, slots=True)
class ExecuteStageCommand:
    tenant_id: str
    assessment_id: str
    stage_type: str
    actor: str


@dataclass(frozen=True, slots=True)
class RecordStageCompletionCommand:
    tenant_id: str
    assessment_id: str
    stage_type: str
    stage_result_ref: str | None
    actor: str


@dataclass(frozen=True, slots=True)
class RecordStageFailureCommand:
    tenant_id: str
    assessment_id: str
    stage_type: str
    error: str
    actor: str


@dataclass(frozen=True, slots=True)
class AdvanceAssessmentCommand:
    tenant_id: str
    assessment_id: str
    actor: str
