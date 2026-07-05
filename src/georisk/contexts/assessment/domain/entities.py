"""The Assessment aggregate — the platform's aggregate root (Domain Model
§1). Pure Python, no SQLAlchemy, no I/O (Clean Architecture's domain
layer). Every state-changing method enforces ``value_objects.LEGAL_TRANSITIONS``
itself; there is no way to set ``status`` directly from outside this class
— "No direct state mutation" is structural here, not a convention (the
field has no public setter path other than through these methods; the
repository/mapper layer is the only other code that touches it directly,
and that's persistence marshalling, not a business transition).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from georisk.contexts.assessment.domain.errors import (
    IllegalAssessmentStatusTransitionError,
    IllegalStageExecutionTransitionError,
    WorkflowNotCompleteError,
)
from georisk.contexts.assessment.domain.events import (
    AssessmentArchived,
    AssessmentCancelled,
    AssessmentCreated,
    AssessmentStageAdvanced,
    StageExecutionCompleted,
    StageExecutionFailed,
    StageExecutionStarted,
    WorkflowStarted,
)
from georisk.contexts.assessment.domain.value_objects import (
    LEGAL_TRANSITIONS,
    AssessmentId,
    AssessmentStatus,
    HazardType,
)
from georisk.contexts.assessment.domain.workflow_value_objects import (
    StageExecutionStatus,
    StageType,
    WorkflowProgress,
)
from georisk.contexts.identity.domain.value_objects import TenantId, UserId


@dataclass(slots=True)
class Assessment:
    id: AssessmentId
    tenant_id: TenantId
    name: str
    hazard_type: HazardType
    status: AssessmentStatus
    created_by: UserId
    created_at: datetime
    updated_at: datetime
    cancellation_reason: str = ""
    # Optimistic concurrency (Application Layer §9) — incremented by the
    # repository on every save; checked before a transition is persisted.
    version: int = field(default=0)
    # Workflow Engine (Roadmap Sprint 3). ``workflow_progress`` is Domain
    # Model §1's ``WorkflowProgress`` value object, embedded directly on
    # this aggregate (not a separate table/aggregate) — the Workflow
    # Engine reads and updates it only through the methods below, never by
    # assigning the field directly, exactly like ``status`` above.
    workflow_template_id: str | None = None
    workflow_progress: WorkflowProgress = field(default_factory=WorkflowProgress)

    @classmethod
    def create(
        cls, *, tenant_id: TenantId, name: str, hazard_type: HazardType, created_by: UserId
    ) -> tuple[Assessment, AssessmentCreated]:
        if not name.strip():
            raise ValueError("Assessment name must not be blank")

        now = datetime.now(UTC)
        assessment = cls(
            id=AssessmentId.new(),
            tenant_id=tenant_id,
            name=name,
            hazard_type=hazard_type,
            status=AssessmentStatus.DRAFT,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        event = AssessmentCreated(
            assessment_id=str(assessment.id),
            tenant_id=str(tenant_id),
            hazard_type=hazard_type.value,
            name=name,
            created_by=str(created_by),
        )
        return assessment, event

    def _transition(
        self, new_status: AssessmentStatus, *, changed_by: str
    ) -> AssessmentStageAdvanced:
        legal = LEGAL_TRANSITIONS.get(self.status, frozenset())
        if new_status not in legal:
            raise IllegalAssessmentStatusTransitionError(
                f"Assessment {self.id} cannot transition from {self.status} to {new_status}"
            )
        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.now(UTC)
        return AssessmentStageAdvanced(
            assessment_id=str(self.id),
            tenant_id=str(self.tenant_id),
            from_status=old_status.value,
            to_status=new_status.value,
            changed_by=changed_by,
        )

    def mark_ready(self, *, changed_by: str) -> AssessmentStageAdvanced:
        return self._transition(AssessmentStatus.READY, changed_by=changed_by)

    def start(self, *, changed_by: str) -> AssessmentStageAdvanced:
        return self._transition(AssessmentStatus.RUNNING, changed_by=changed_by)

    def mark_validated(self, *, changed_by: str) -> AssessmentStageAdvanced:
        return self._transition(AssessmentStatus.VALIDATED, changed_by=changed_by)

    def mark_reported(self, *, changed_by: str) -> AssessmentStageAdvanced:
        return self._transition(AssessmentStatus.REPORTED, changed_by=changed_by)

    def archive(self, *, archived_by: str) -> AssessmentArchived:
        legal = LEGAL_TRANSITIONS.get(self.status, frozenset())
        if AssessmentStatus.ARCHIVED not in legal:
            raise IllegalAssessmentStatusTransitionError(
                f"Assessment {self.id} cannot be archived from status {self.status}"
            )
        self.status = AssessmentStatus.ARCHIVED
        self.updated_at = datetime.now(UTC)
        return AssessmentArchived(
            assessment_id=str(self.id), tenant_id=str(self.tenant_id), archived_by=archived_by
        )

    def cancel(self, *, reason: str, cancelled_by: str) -> AssessmentCancelled:
        legal = LEGAL_TRANSITIONS.get(self.status, frozenset())
        if AssessmentStatus.CANCELLED not in legal:
            raise IllegalAssessmentStatusTransitionError(
                f"Assessment {self.id} cannot be cancelled from status {self.status}"
            )
        if not reason.strip():
            raise ValueError("A cancellation reason is required")
        self.status = AssessmentStatus.CANCELLED
        self.cancellation_reason = reason
        self.updated_at = datetime.now(UTC)
        return AssessmentCancelled(
            assessment_id=str(self.id),
            tenant_id=str(self.tenant_id),
            reason=reason,
            cancelled_by=cancelled_by,
        )

    def is_terminal(self) -> bool:
        return self.status in (AssessmentStatus.ARCHIVED, AssessmentStatus.CANCELLED)

    # --- Workflow Engine (Roadmap Sprint 3) --------------------------------
    #
    # These five methods are the *only* way ``workflow_template_id`` and
    # ``workflow_progress`` ever change. The Workflow Engine application
    # service (``application/workflow_engine.py``) never sets either field
    # itself — it always goes through one of ``StartWorkflowCommand``,
    # ``ExecuteStageCommand``, ``RecordStageCompletionCommand``,
    # ``RecordStageFailureCommand`` or ``AdvanceAssessmentCommand``, each of
    # which calls exactly one of these. Deliberately DAG-agnostic: none of
    # these methods know about ``WorkflowTemplate.stage_definitions`` or
    # predecessor relationships — the caller (Workflow Engine, which *does*
    # read the template) is responsible for only invoking ``start_stage``
    # once a stage is actually runnable, and for passing the correct
    # ``required_stage_types`` into ``advance_past_running``. This keeps the
    # Assessment aggregate root ignorant of any specific template's shape,
    # matching Domain Model §1's separation between the aggregate and the
    # orchestration graph it's merely tracking progress against.

    def start_workflow(
        self,
        *,
        workflow_template_id: str,
        stage_types: frozenset[StageType],
        changed_by: str,
    ) -> tuple[AssessmentStageAdvanced, WorkflowStarted]:
        """READY -> RUNNING, binding this assessment to a specific
        (published) ``WorkflowTemplate`` and initializing one NOT_STARTED
        progress entry per stage it defines. Reuses ``_transition`` for the
        status change, so the underlying FSM guard (Domain Model §6) is
        identical to the plain ``start()`` path used by assessments that
        don't go through the Workflow Engine at all.
        """
        transition_event = self._transition(AssessmentStatus.RUNNING, changed_by=changed_by)
        self.workflow_template_id = workflow_template_id
        self.workflow_progress = self.workflow_progress.initialize(
            workflow_template_id, stage_types
        )
        started_event = WorkflowStarted(
            assessment_id=str(self.id),
            tenant_id=str(self.tenant_id),
            workflow_template_id=workflow_template_id,
            stage_types=sorted(st.value for st in stage_types),
            started_by=changed_by,
        )
        return transition_event, started_event

    def start_stage(self, stage_type: StageType, *, triggered_by: str) -> StageExecutionStarted:
        if self.status != AssessmentStatus.RUNNING:
            raise IllegalAssessmentStatusTransitionError(
                f"Assessment {self.id} is not RUNNING (status={self.status}); "
                f"cannot start stage {stage_type}"
            )
        entry = self.workflow_progress.get(stage_type)
        try:
            new_entry = entry.advance_to(StageExecutionStatus.RUNNING, now=datetime.now(UTC))
        except ValueError as exc:
            raise IllegalStageExecutionTransitionError(str(exc)) from exc
        self.workflow_progress = self.workflow_progress.with_entry(new_entry)
        self.updated_at = datetime.now(UTC)
        return StageExecutionStarted(
            assessment_id=str(self.id),
            tenant_id=str(self.tenant_id),
            stage_type=stage_type.value,
            attempt=new_entry.attempt_count,
            triggered_by=triggered_by,
        )

    def complete_stage(
        self, stage_type: StageType, *, stage_result_ref: str | None, changed_by: str
    ) -> StageExecutionCompleted:
        if self.status != AssessmentStatus.RUNNING:
            raise IllegalAssessmentStatusTransitionError(
                f"Assessment {self.id} is not RUNNING (status={self.status}); "
                f"cannot complete stage {stage_type}"
            )
        entry = self.workflow_progress.get(stage_type)
        try:
            new_entry = entry.advance_to(
                StageExecutionStatus.COMPLETE,
                now=datetime.now(UTC),
                stage_result_ref=stage_result_ref,
            )
        except ValueError as exc:
            raise IllegalStageExecutionTransitionError(str(exc)) from exc
        self.workflow_progress = self.workflow_progress.with_entry(new_entry)
        self.updated_at = datetime.now(UTC)
        return StageExecutionCompleted(
            assessment_id=str(self.id),
            tenant_id=str(self.tenant_id),
            stage_type=stage_type.value,
            stage_result_ref=stage_result_ref,
        )

    def fail_stage(
        self, stage_type: StageType, *, error: str, changed_by: str
    ) -> StageExecutionFailed:
        if self.status != AssessmentStatus.RUNNING:
            raise IllegalAssessmentStatusTransitionError(
                f"Assessment {self.id} is not RUNNING (status={self.status}); "
                f"cannot fail stage {stage_type}"
            )
        entry = self.workflow_progress.get(stage_type)
        try:
            new_entry = entry.advance_to(
                StageExecutionStatus.FAILED, now=datetime.now(UTC), error=error
            )
        except ValueError as exc:
            raise IllegalStageExecutionTransitionError(str(exc)) from exc
        self.workflow_progress = self.workflow_progress.with_entry(new_entry)
        self.updated_at = datetime.now(UTC)
        return StageExecutionFailed(
            assessment_id=str(self.id),
            tenant_id=str(self.tenant_id),
            stage_type=stage_type.value,
            attempt=new_entry.attempt_count,
            error=error,
        )

    def advance_past_running(
        self, *, required_stage_types: frozenset[StageType], changed_by: str
    ) -> AssessmentStageAdvanced:
        """RUNNING -> VALIDATED, guarded by "every required stage is
        COMPLETE" — the invariant enforced here, on the aggregate, rather
        than trusted from the caller (Workflow Engine determines *which*
        stages are required by reading the template, but the aggregate
        itself is what refuses to advance if that set isn't actually
        satisfied in its own ``workflow_progress``).
        """
        if not self.workflow_progress.all_complete(required_stage_types):
            raise WorkflowNotCompleteError(
                f"Assessment {self.id} cannot advance past RUNNING: not all "
                f"required stages are COMPLETE"
            )
        return self._transition(AssessmentStatus.VALIDATED, changed_by=changed_by)
