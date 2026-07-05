"""Assessment domain events (Domain Model §5's catalog, the slice this
context owns). Emitted by command handlers into the outbox
(``db/outbox_writer.py``) within the same transaction as the aggregate
change that caused them — this sprint's "Assessment Audit Events"
requirement, satisfied by the same mechanism proven in Sprint 1, applied
to a second aggregate.

``AssessmentStageAdvanced`` is deliberately the ONE generic event covering
every forward-progress transition (DRAFT->READY, READY->RUNNING,
RUNNING->VALIDATED, VALIDATED->REPORTED) rather than one event class per
transition — this matches Domain Model §5's own catalog exactly, which
names `AssessmentStageAdvanced { assessmentId, fromStatus, toStatus }` as
a single reusable event. Archiving and cancellation get their own named
events (`AssessmentArchived`, `AssessmentCancelled`) because Domain Model
§5 calls them out specifically — archiving has a distinct downstream
meaning (read-only lock) and cancellation carries a reason.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class AssessmentCreated:
    event_type: ClassVar[str] = "assessment.AssessmentCreated"
    assessment_id: str
    tenant_id: str
    hazard_type: str
    name: str
    created_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class AssessmentStageAdvanced:
    event_type: ClassVar[str] = "assessment.AssessmentStageAdvanced"
    assessment_id: str
    tenant_id: str
    from_status: str
    to_status: str
    changed_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class AssessmentArchived:
    event_type: ClassVar[str] = "assessment.AssessmentArchived"
    assessment_id: str
    tenant_id: str
    archived_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class AssessmentCancelled:
    event_type: ClassVar[str] = "assessment.AssessmentCancelled"
    assessment_id: str
    tenant_id: str
    reason: str
    cancelled_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


# --- Workflow Engine (Roadmap Sprint 3) ------------------------------------
#
# WorkflowTemplate events carry no tenant_id — templates are a global,
# platform-owned catalog (Platform Architecture §5), not tenant data.
# Assessment/stage events below all carry tenant_id, same as the events
# above, and are appended to the outbox against aggregate_type="Assessment"
# (this sprint's "Workflow Audit Events" / "Domain Events Integration"
# requirements #12/#5 — same outbox mechanism, no new plumbing).


@dataclass(frozen=True, slots=True)
class WorkflowTemplateCreated:
    event_type: ClassVar[str] = "assessment.WorkflowTemplateCreated"
    workflow_template_id: str
    hazard_type: str
    name: str
    version: int
    stage_types: list[str]

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class WorkflowTemplatePublished:
    event_type: ClassVar[str] = "assessment.WorkflowTemplatePublished"
    workflow_template_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class WorkflowStarted:
    event_type: ClassVar[str] = "assessment.WorkflowStarted"
    assessment_id: str
    tenant_id: str
    workflow_template_id: str
    stage_types: list[str]
    started_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class StageExecutionStarted:
    event_type: ClassVar[str] = "assessment.StageExecutionStarted"
    assessment_id: str
    tenant_id: str
    stage_type: str
    attempt: int
    triggered_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class StageExecutionCompleted:
    event_type: ClassVar[str] = "assessment.StageExecutionCompleted"
    assessment_id: str
    tenant_id: str
    stage_type: str
    stage_result_ref: str | None

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class StageExecutionFailed:
    event_type: ClassVar[str] = "assessment.StageExecutionFailed"
    assessment_id: str
    tenant_id: str
    stage_type: str
    attempt: int
    error: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}
