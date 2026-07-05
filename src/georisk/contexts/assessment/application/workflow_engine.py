"""The Workflow Engine (Application Layer §5; Sprint 3 requirements #3
"Workflow Engine Service", #4 "Assessment Orchestration", #7/#8 parallel and
sequential execution, #9/#10 manual and automatic triggers, #11 retry).

Structural guarantee this whole module is built around: **the engine never
touches an ``Assessment`` field**. Every step below is one of the command
handlers in ``workflow_handlers.py``, each its own transaction acquired via
``Database.session()`` — the identical multi-transaction-orchestrator shape
Identity's tenant-registration flow already established in Sprint 1 for "one
application-layer operation, several aggregate-transactions in sequence".
The engine's only vocabulary for changing anything is "issue this command
and wait for it to commit" — never a direct assignment, never reaching past
a handler into the aggregate itself.

"Reacts to events" is implemented *synchronously*, in-process: the caller of
each command explicitly calls into the next reaction step right after that
command's handler commits, rather than a separate process polling the
outbox table. Infrastructure Architecture §9 explicitly sanctions this for a
single-process deployment ("can run essentially immediately after commit,
giving near-real-time projection updates without weakening the durability
guarantee") — a genuine async outbox relay (Celery-dispatched, cross-process)
is not part of this sprint's named component list and would be premature
before any stage actually does asynchronous work (see ``StageExecutor``
below). Every event this engine "reacts to" was still durably written to the
outbox by the command that produced it — nothing here depends on the
in-process call chain for correctness, only for latency.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from georisk.contexts.assessment.application.workflow_commands import (
    AdvanceAssessmentCommand,
    ExecuteStageCommand,
    RecordStageCompletionCommand,
    RecordStageFailureCommand,
    StartWorkflowCommand,
)
from georisk.contexts.assessment.application.workflow_handlers import (
    AdvanceAssessmentHandler,
    ExecuteStageHandler,
    RecordStageCompletionHandler,
    RecordStageFailureHandler,
    StartWorkflowHandler,
)
from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.errors import AssessmentNotFoundError
from georisk.contexts.assessment.domain.value_objects import AssessmentId
from georisk.contexts.assessment.domain.workflow_template import (
    WorkflowTemplate,
    WorkflowTemplateId,
)
from georisk.contexts.assessment.domain.workflow_value_objects import (
    StageExecutionStatus,
    StageType,
    TriggerMode,
)
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.assessment.infrastructure.workflow_repositories import (
    SqlAlchemyWorkflowTemplateRepository,
)
from georisk.db.session import Database

logger = logging.getLogger("georisk.workflow_engine")

SYSTEM_ACTOR = "system:workflow-engine"


@dataclass(frozen=True, slots=True)
class StageExecutionOutcome:
    success: bool
    stage_result_ref: str | None = None
    error: str | None = None


class StageExecutor(Protocol):
    """Seam for a real hazard/exposure/vulnerability/risk calculator to be
    plugged in by a later sprint (Roadmap Sprint 4/5+) — this sprint
    supplies only the stub below. "Hazard formulas... GIS logic... AI
    prediction" are explicitly out of scope here; the Workflow Engine
    itself never has a hazard-type-specific branch (Platform Architecture
    §5) — it only ever calls whatever ``StageExecutor`` it was given.
    """

    async def execute(
        self, stage_type: StageType, *, assessment_id: str
    ) -> StageExecutionOutcome: ...


class ImmediateSuccessStageExecutor:
    """This sprint's stub. Proves the scheduling/orchestration mechanics —
    parallel fan-out, sequential dependency waiting, manual vs. automatic
    dispatch, retry — are correct without pretending to compute anything
    real (Roadmap's own Sprint 3 framing: prove the engine against a
    trivial stub before any real hazard science exists).
    """

    async def execute(self, stage_type: StageType, *, assessment_id: str) -> StageExecutionOutcome:
        return StageExecutionOutcome(
            success=True, stage_result_ref=f"stub:{assessment_id}:{stage_type.value}"
        )


class WorkflowEngine:
    def __init__(self, db: Database, stage_executor: StageExecutor) -> None:
        self._db = db
        self._stage_executor = stage_executor

    async def start_workflow(
        self, *, tenant_id: str, assessment_id: str, workflow_template_id: str, actor: str
    ) -> None:
        async with self._db.session() as session:
            await StartWorkflowHandler(session).handle(
                StartWorkflowCommand(
                    tenant_id=tenant_id,
                    assessment_id=assessment_id,
                    workflow_template_id=workflow_template_id,
                    actor=actor,
                )
            )
        await self._dispatch_runnable_stages(tenant_id=tenant_id, assessment_id=assessment_id)

    async def execute_stage(
        self, *, tenant_id: str, assessment_id: str, stage_type: StageType, actor: str
    ) -> None:
        """Public entry point for BOTH manual (``actor`` = a real user id —
        the API route calls this directly, requirement #9) and automatic
        (``actor`` = ``SYSTEM_ACTOR`` — this engine calls itself,
        requirement #10) stage triggers. Same mechanism, different caller;
        the command handler and the aggregate underneath have no notion of
        "manual" vs "automatic" at all.
        """
        async with self._db.session() as session:
            await ExecuteStageHandler(session).handle(
                ExecuteStageCommand(
                    tenant_id=tenant_id,
                    assessment_id=assessment_id,
                    stage_type=stage_type.value,
                    actor=actor,
                )
            )

        outcome = await self._stage_executor.execute(stage_type, assessment_id=assessment_id)

        async with self._db.session() as session:
            if outcome.success:
                await RecordStageCompletionHandler(session).handle(
                    RecordStageCompletionCommand(
                        tenant_id=tenant_id,
                        assessment_id=assessment_id,
                        stage_type=stage_type.value,
                        stage_result_ref=outcome.stage_result_ref,
                        actor=actor,
                    )
                )
            else:
                await RecordStageFailureHandler(session).handle(
                    RecordStageFailureCommand(
                        tenant_id=tenant_id,
                        assessment_id=assessment_id,
                        stage_type=stage_type.value,
                        error=outcome.error or "stage execution failed",
                        actor=actor,
                    )
                )

        if outcome.success:
            await self._on_stage_completed(tenant_id=tenant_id, assessment_id=assessment_id)
        else:
            await self._on_stage_failed(
                tenant_id=tenant_id, assessment_id=assessment_id, stage_type=stage_type
            )

    # --- internal reaction steps -------------------------------------------

    async def _load_assessment_and_template(
        self, tenant_id: str, assessment_id: str
    ) -> tuple[Assessment, WorkflowTemplate | None]:
        async with self._db.session() as session:
            assessment_repo = SqlAlchemyAssessmentRepository(session)
            assessment = await assessment_repo.get_by_id(AssessmentId.from_string(assessment_id))
            if assessment is None or str(assessment.tenant_id) != tenant_id:
                raise AssessmentNotFoundError(f"Assessment {assessment_id} not found")
            template = None
            if assessment.workflow_template_id:
                template_repo = SqlAlchemyWorkflowTemplateRepository(session)
                template = await template_repo.get_by_id(
                    WorkflowTemplateId.from_string(assessment.workflow_template_id)
                )
            return assessment, template

    async def _dispatch_runnable_stages(self, *, tenant_id: str, assessment_id: str) -> None:
        """Dispatches every currently-runnable AUTOMATIC stage — the
        mechanism behind parallel fan-out (requirement #7): Hazard,
        Exposure and Vulnerability all have no unmet predecessors at once,
        so all three are in ``automatic`` together, not gated behind one
        another.

        Because ``execute_stage`` runs synchronously end-to-end with this
        sprint's stub executor, dispatching the first stage in the loop can
        itself complete, cascade into ``_on_stage_completed``, and
        recursively call back into this same method — which would find the
        *other* siblings (Exposure, Vulnerability) already runnable and
        dispatch them too, before this loop's own iterator gets to them.
        Each iteration therefore re-checks the stage's live status
        immediately before dispatching it and skips anything a nested
        recursive call already started or finished — without this check,
        the outer loop would call ``execute_stage`` a second time on a
        stage already COMPLETE, which is an illegal transition (caught by
        ``test_parallel_flow_runs_to_completion_and_advances_assessment``
        failing against real Postgres during this sprint's validation, not
        assumed correct from the code reading right in isolation).
        """
        assessment, template = await self._load_assessment_and_template(tenant_id, assessment_id)
        if template is None:
            return
        runnable = template.runnable_stages(assessment.workflow_progress)
        automatic = [sd for sd in runnable if sd.trigger_mode is TriggerMode.AUTOMATIC]
        for stage_def in automatic:
            current_assessment, _ = await self._load_assessment_and_template(
                tenant_id, assessment_id
            )
            current_status = current_assessment.workflow_progress.get(stage_def.stage_type).status
            if current_status not in (
                StageExecutionStatus.NOT_STARTED,
                StageExecutionStatus.FAILED,
            ):
                continue
            await self.execute_stage(
                tenant_id=tenant_id,
                assessment_id=assessment_id,
                stage_type=stage_def.stage_type,
                actor=SYSTEM_ACTOR,
            )

    async def _on_stage_completed(self, *, tenant_id: str, assessment_id: str) -> None:
        assessment, template = await self._load_assessment_and_template(tenant_id, assessment_id)
        if template is None:
            return
        if assessment.workflow_progress.all_complete(template.required_stage_types()):
            async with self._db.session() as session:
                await AdvanceAssessmentHandler(session).handle(
                    AdvanceAssessmentCommand(
                        tenant_id=tenant_id, assessment_id=assessment_id, actor=SYSTEM_ACTOR
                    )
                )
        else:
            await self._dispatch_runnable_stages(tenant_id=tenant_id, assessment_id=assessment_id)

    async def _on_stage_failed(
        self, *, tenant_id: str, assessment_id: str, stage_type: StageType
    ) -> None:
        assessment, template = await self._load_assessment_and_template(tenant_id, assessment_id)
        if template is None:
            return
        stage_def = template.get_stage_definition(stage_type)
        entry = assessment.workflow_progress.get(stage_type)
        if stage_def is not None and entry.attempt_count < stage_def.max_attempts:
            logger.info(
                "Retrying stage %s for assessment %s (attempt %d/%d)",
                stage_type,
                assessment_id,
                entry.attempt_count + 1,
                stage_def.max_attempts,
            )
            await self.execute_stage(
                tenant_id=tenant_id,
                assessment_id=assessment_id,
                stage_type=stage_type,
                actor=SYSTEM_ACTOR,
            )
        else:
            logger.warning(
                "Stage %s for assessment %s exhausted its retry budget; "
                "workflow blocked pending manual intervention",
                stage_type,
                assessment_id,
            )
