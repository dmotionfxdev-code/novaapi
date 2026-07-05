"""Command handlers for WorkflowTemplate authoring and for Workflow/Stage
execution against ``Assessment``. Every execution handler follows the
identical one-transaction, load -> tenant-scope check -> invoke-the-entity-
method-that-enforces-the-FSM -> save-with-optimistic-concurrency -> append-
event -> commit shape as ``handlers.py``'s Sprint 2 handlers — the entity
method invoked just happens to be one of the new workflow methods on
``Assessment`` (``start_workflow``/``start_stage``/``complete_stage``/
``fail_stage``/``advance_past_running``) rather than a plain lifecycle
transition. No handler here ever sets an ``Assessment`` field directly.

These handlers are deliberately "dumb": each one does exactly one command's
worth of work and returns. Sequencing several of them together (dispatch the
next wave of runnable stages, retry a failed one, advance once everything's
done) is ``WorkflowEngine``'s job (``workflow_engine.py``), not something any
handler does on its own — keeping the "Workflow Engine only reacts to events
and issues commands" / "never directly mutates Assessment state" constraints
structurally true: the engine's only way to affect an assessment is calling
one of these handlers, exactly like a user-facing API route would.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.assessment.application.handlers import _load_or_404
from georisk.contexts.assessment.application.workflow_commands import (
    AdvanceAssessmentCommand,
    CreateWorkflowTemplateCommand,
    ExecuteStageCommand,
    PublishWorkflowTemplateCommand,
    RecordStageCompletionCommand,
    RecordStageFailureCommand,
    StartWorkflowCommand,
)
from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.errors import WorkflowTemplateNotFoundError
from georisk.contexts.assessment.domain.value_objects import HazardType
from georisk.contexts.assessment.domain.workflow_template import (
    WorkflowTemplate,
    WorkflowTemplateId,
)
from georisk.contexts.assessment.domain.workflow_value_objects import (
    StageDefinition,
    StageType,
    TriggerMode,
    WorkflowTemplateStatus,
)
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.assessment.infrastructure.workflow_repositories import (
    SqlAlchemyWorkflowTemplateRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.db.outbox_writer import append_event
from georisk.shared_kernel.errors import GuardRejectedError


def _stage_definitions_from_dicts(raw: list[dict]) -> tuple[StageDefinition, ...]:
    return tuple(
        StageDefinition(
            stage_type=StageType(sd["stage_type"]),
            required_predecessors=frozenset(
                StageType(p) for p in sd.get("required_predecessors", [])
            ),
            trigger_mode=TriggerMode(sd.get("trigger_mode", "AUTOMATIC")),
            max_attempts=sd.get("max_attempts", 3),
        )
        for sd in raw
    )


class CreateWorkflowTemplateHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: CreateWorkflowTemplateCommand) -> WorkflowTemplate:
        repo = SqlAlchemyWorkflowTemplateRepository(self._session)
        template, event = WorkflowTemplate.create(
            hazard_type=HazardType(command.hazard_type),
            name=command.name,
            stage_definitions=_stage_definitions_from_dicts(command.stage_definitions),
        )
        await repo.save(template)
        await append_event(
            self._session,
            aggregate_type="WorkflowTemplate",
            aggregate_id=str(template.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=None,
        )
        await self._session.commit()
        return template


class PublishWorkflowTemplateHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: PublishWorkflowTemplateCommand) -> WorkflowTemplate:
        repo = SqlAlchemyWorkflowTemplateRepository(self._session)
        template = await repo.get_by_id(
            WorkflowTemplateId.from_string(command.workflow_template_id)
        )
        if template is None:
            raise WorkflowTemplateNotFoundError(
                f"WorkflowTemplate {command.workflow_template_id} not found"
            )
        event = template.publish()
        await repo.save(template)
        await append_event(
            self._session,
            aggregate_type="WorkflowTemplate",
            aggregate_id=str(template.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=None,
        )
        await self._session.commit()
        return template


class StartWorkflowHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: StartWorkflowCommand) -> Assessment:
        assessment_repo = SqlAlchemyAssessmentRepository(self._session)
        template_repo = SqlAlchemyWorkflowTemplateRepository(self._session)
        tenant_id = TenantId.from_string(command.tenant_id)
        assessment = await _load_or_404(assessment_repo, command.assessment_id, tenant_id)

        template = await template_repo.get_by_id(
            WorkflowTemplateId.from_string(command.workflow_template_id)
        )
        if template is None:
            raise WorkflowTemplateNotFoundError(
                f"WorkflowTemplate {command.workflow_template_id} not found"
            )
        if template.status != WorkflowTemplateStatus.PUBLISHED:
            raise GuardRejectedError(f"WorkflowTemplate {template.id} is not PUBLISHED")
        if template.hazard_type != assessment.hazard_type:
            raise GuardRejectedError(
                f"WorkflowTemplate {template.id} hazard_type ({template.hazard_type}) does not "
                f"match Assessment {assessment.id} hazard_type ({assessment.hazard_type})"
            )

        transition_event, started_event = assessment.start_workflow(
            workflow_template_id=str(template.id),
            stage_types=template.required_stage_types(),
            changed_by=command.actor,
        )
        await assessment_repo.save(assessment, expected_version=assessment.version)
        for event in (transition_event, started_event):
            await append_event(
                self._session,
                aggregate_type="Assessment",
                aggregate_id=str(assessment.id),
                event_type=event.event_type,
                payload=event.payload(),
                tenant_id=tenant_id.value,
            )
        await self._session.commit()
        return assessment


class ExecuteStageHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: ExecuteStageCommand) -> Assessment:
        repo = SqlAlchemyAssessmentRepository(self._session)
        tenant_id = TenantId.from_string(command.tenant_id)
        assessment = await _load_or_404(repo, command.assessment_id, tenant_id)

        event = assessment.start_stage(StageType(command.stage_type), triggered_by=command.actor)
        await repo.save(assessment, expected_version=assessment.version)
        await append_event(
            self._session,
            aggregate_type="Assessment",
            aggregate_id=str(assessment.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return assessment


class RecordStageCompletionHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: RecordStageCompletionCommand) -> Assessment:
        repo = SqlAlchemyAssessmentRepository(self._session)
        tenant_id = TenantId.from_string(command.tenant_id)
        assessment = await _load_or_404(repo, command.assessment_id, tenant_id)

        event = assessment.complete_stage(
            StageType(command.stage_type),
            stage_result_ref=command.stage_result_ref,
            changed_by=command.actor,
        )
        await repo.save(assessment, expected_version=assessment.version)
        await append_event(
            self._session,
            aggregate_type="Assessment",
            aggregate_id=str(assessment.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return assessment


class RecordStageFailureHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: RecordStageFailureCommand) -> Assessment:
        repo = SqlAlchemyAssessmentRepository(self._session)
        tenant_id = TenantId.from_string(command.tenant_id)
        assessment = await _load_or_404(repo, command.assessment_id, tenant_id)

        event = assessment.fail_stage(
            StageType(command.stage_type), error=command.error, changed_by=command.actor
        )
        await repo.save(assessment, expected_version=assessment.version)
        await append_event(
            self._session,
            aggregate_type="Assessment",
            aggregate_id=str(assessment.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return assessment


class AdvanceAssessmentHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: AdvanceAssessmentCommand) -> Assessment:
        assessment_repo = SqlAlchemyAssessmentRepository(self._session)
        template_repo = SqlAlchemyWorkflowTemplateRepository(self._session)
        tenant_id = TenantId.from_string(command.tenant_id)
        assessment = await _load_or_404(assessment_repo, command.assessment_id, tenant_id)

        if assessment.workflow_template_id is None:
            raise GuardRejectedError(f"Assessment {assessment.id} has no workflow bound")
        template = await template_repo.get_by_id(
            WorkflowTemplateId.from_string(assessment.workflow_template_id)
        )
        if template is None:
            raise WorkflowTemplateNotFoundError(
                f"WorkflowTemplate {assessment.workflow_template_id} not found"
            )

        event = assessment.advance_past_running(
            required_stage_types=template.required_stage_types(), changed_by=command.actor
        )
        await assessment_repo.save(assessment, expected_version=assessment.version)
        await append_event(
            self._session,
            aggregate_type="Assessment",
            aggregate_id=str(assessment.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return assessment
