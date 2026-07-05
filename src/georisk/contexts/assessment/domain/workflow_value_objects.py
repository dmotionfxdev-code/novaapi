"""Value objects for the Workflow Engine (Domain Model §1/§6, Application
Layer §5) — same "Assessment Orchestration" bounded context as
``entities.Assessment``, not a separate module/context (Domain Model §1's
table lists ``WorkflowTemplate`` under Assessment Orchestration explicitly).
``WorkflowTemplate`` itself (the DAG-authoring aggregate) lives in
``workflow_template.py``; the types here are the smaller immutable pieces
it, and ``Assessment.workflow_progress``, are built from.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum


class StageType(StrEnum):
    """Domain Model §3 describes this as open/extensible per hazard type;
    Sprint 3 enumerated only five generic orchestration stages (Hazard,
    Exposure, Vulnerability, Risk, Validation) — the same closed-enum-now,
    extend-later posture already used for ``value_objects.HazardType``.
    ``RESILIENCE`` was added in Sprint 5 (FIRAS Strategy): the Application
    Layer's own worked trace names it explicitly as a stage parallel to
    Risk (both become runnable once Vulnerability completes; Resilience's
    real formula dependency is Vulnerability/Insecurity's sub-index scores
    only, never Risk's output — confirmed against the ported legacy
    formulas), so it cannot be folded into an existing stage without
    misrepresenting the actual DAG. This is still the only structural
    change Sprint 5 makes anywhere under ``contexts.assessment`` — every
    hazard-specific calculator lives entirely in
    ``contexts.analysis.strategies.firas``, never here.

    ``FIRE_REGIME``, ``BURN_OCCURRENCE_PROBABILITY``, and ``BURN_SEVERITY``
    were added in Sprint 6 (WRRAS Strategy), approved by
    ``WRRAS_SCOPE_DECISION_LOG.md`` §5: none of the three is consumed by
    Hazard/Exposure/Vulnerability/Risk/Resilience (confirmed by grep of
    every WRRAS formula module, not inference), so they are optional,
    non-gating stages — never a ``required_predecessor`` of anything, and
    a ``WorkflowTemplate`` need not include them at all for an assessment
    to reach ``VALIDATED``. Same "one approved, minimal exception to
    'don't modify Assessment'" precedent ``RESILIENCE`` set in Sprint 5;
    still no other structural change anywhere under
    ``contexts.assessment`` — every WRRAS-specific calculator lives
    entirely in ``contexts.analysis.strategies.wrras``, never here.
    """

    HAZARD = "HAZARD"
    EXPOSURE = "EXPOSURE"
    VULNERABILITY = "VULNERABILITY"
    RISK = "RISK"
    RESILIENCE = "RESILIENCE"
    VALIDATION = "VALIDATION"
    FIRE_REGIME = "FIRE_REGIME"
    BURN_OCCURRENCE_PROBABILITY = "BURN_OCCURRENCE_PROBABILITY"
    BURN_SEVERITY = "BURN_SEVERITY"


class TriggerMode(StrEnum):
    """Application Layer §5 — whether the Workflow Engine dispatches a
    stage the instant it becomes runnable (AUTOMATIC, requirement #10) or
    leaves it NOT_STARTED until a user explicitly issues the run command
    (MANUAL, requirement #9). Both paths converge on the identical
    ``ExecuteStageCommand`` handler — only the issuer/actor differs.
    """

    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"


class StageExecutionStatus(StrEnum):
    """Per-stage mini state machine backing ``StageProgressEntry.status``.
    NOT_STARTED -> RUNNING -> {COMPLETE | FAILED}; FAILED -> RUNNING is the
    retry transition (requirement #11), bounded by
    ``StageDefinition.max_attempts``.
    """

    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


_STAGE_LEGAL_TRANSITIONS: dict[StageExecutionStatus, frozenset[StageExecutionStatus]] = {
    StageExecutionStatus.NOT_STARTED: frozenset({StageExecutionStatus.RUNNING}),
    StageExecutionStatus.RUNNING: frozenset(
        {StageExecutionStatus.COMPLETE, StageExecutionStatus.FAILED}
    ),
    StageExecutionStatus.FAILED: frozenset({StageExecutionStatus.RUNNING}),
    StageExecutionStatus.COMPLETE: frozenset(),
}


class WorkflowTemplateStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"


@dataclass(frozen=True, slots=True)
class StageDefinition:
    """One node in a ``WorkflowTemplate``'s DAG (Domain Model §6). Pure
    data — the Workflow Engine (``application/workflow_engine.py``) is the
    only code that interprets ``required_predecessors`` to decide what's
    runnable; this type has no behavior of its own beyond construction
    validation.
    """

    stage_type: StageType
    required_predecessors: frozenset[StageType] = frozenset()
    trigger_mode: TriggerMode = TriggerMode.AUTOMATIC
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.stage_type in self.required_predecessors:
            raise ValueError(f"{self.stage_type} cannot depend on itself")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")


@dataclass(frozen=True, slots=True)
class StageProgressEntry:
    """Domain Model §6's ``StageProgressEntry`` — one row of the
    ``WorkflowProgress`` projection held on ``Assessment``. Immutable;
    every "update" (``advance_to``) returns a *new* entry rather than
    mutating in place — ``Assessment``'s own methods are the only code
    that reassigns ``workflow_progress`` as a whole, keeping "no direct
    mutation" true for this nested value object too.
    """

    stage_type: StageType
    status: StageExecutionStatus = StageExecutionStatus.NOT_STARTED
    attempt_count: int = 0
    stage_result_ref: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_error: str | None = None

    def advance_to(
        self,
        new_status: StageExecutionStatus,
        *,
        now: datetime,
        stage_result_ref: str | None = None,
        error: str | None = None,
    ) -> StageProgressEntry:
        legal = _STAGE_LEGAL_TRANSITIONS.get(self.status, frozenset())
        if new_status not in legal:
            raise ValueError(
                f"Stage {self.stage_type} cannot transition from {self.status} to {new_status}"
            )
        if new_status is StageExecutionStatus.RUNNING:
            return replace(
                self,
                status=new_status,
                attempt_count=self.attempt_count + 1,
                started_at=now,
                last_error=None,
            )
        if new_status is StageExecutionStatus.COMPLETE:
            return replace(
                self, status=new_status, completed_at=now, stage_result_ref=stage_result_ref
            )
        # new_status is FAILED — the only remaining legal target.
        return replace(self, status=new_status, last_error=error)


@dataclass(frozen=True, slots=True)
class WorkflowProgress:
    """Domain Model §1's ``WorkflowProgress`` (VO) — embedded directly on
    ``Assessment``, not a separate aggregate/table. A
    ``Map<StageType, StageProgressEntry>`` represented as a tuple for
    hashability; lookups always go through ``get``, never direct indexing,
    so a stage with no entry yet (never started) and a stage that exists
    are handled by the same code path.
    """

    workflow_template_id: str | None = None
    entries: tuple[StageProgressEntry, ...] = ()

    def get(self, stage_type: StageType) -> StageProgressEntry:
        for entry in self.entries:
            if entry.stage_type == stage_type:
                return entry
        return StageProgressEntry(stage_type=stage_type)

    def with_entry(self, entry: StageProgressEntry) -> WorkflowProgress:
        remaining = tuple(e for e in self.entries if e.stage_type != entry.stage_type)
        return replace(self, entries=(*remaining, entry))

    def is_complete(self, stage_type: StageType) -> bool:
        return self.get(stage_type).status == StageExecutionStatus.COMPLETE

    def all_complete(self, stage_types: frozenset[StageType]) -> bool:
        return all(self.is_complete(st) for st in stage_types)

    def initialize(
        self, workflow_template_id: str, stage_types: frozenset[StageType]
    ) -> WorkflowProgress:
        return WorkflowProgress(
            workflow_template_id=workflow_template_id,
            entries=tuple(StageProgressEntry(stage_type=st) for st in sorted(stage_types, key=str)),
        )
