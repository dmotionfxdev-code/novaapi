"""Assessment command handlers — each one transaction, one aggregate
(``Assessment``), per Application Layer §9. Every handler follows the same
shape: load -> tenant-scope check -> invoke the entity method that enforces
the FSM -> save with optimistic concurrency -> append the resulting event
to the outbox -> commit. No handler ever sets ``.status`` directly; the
entity method is the only path (this sprint's "No direct state mutation"
and "all transitions through commands" requirements, made structural).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.assessment.application.commands import (
    ArchiveAssessment,
    CancelAssessment,
    CreateAssessment,
    MarkAssessmentReady,
    ReportAssessment,
    StartAssessment,
    ValidateAssessment,
)
from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.errors import AssessmentNotFoundError
from georisk.contexts.assessment.domain.value_objects import AssessmentId, HazardType
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.db.outbox_writer import append_event


def _assert_same_tenant(assessment: Assessment, tenant_id: TenantId) -> None:
    """Interim, application-layer tenant scoping (Roadmap Sprint 1/2 — real
    database-level enforcement via Row-Level Security lands in Sprint 11,
    Infrastructure Architecture §6). Fails exactly like "not found" — never
    revealing that an assessment with this ID exists in a *different*
    tenant (API Resource Model §9).
    """
    if assessment.tenant_id != tenant_id:
        raise AssessmentNotFoundError(f"Assessment {assessment.id} not found")


async def _load_or_404(
    repo: SqlAlchemyAssessmentRepository, assessment_id: str, tenant_id: TenantId
) -> Assessment:
    assessment = await repo.get_by_id(AssessmentId.from_string(assessment_id))
    if assessment is None:
        raise AssessmentNotFoundError(f"Assessment {assessment_id} not found")
    _assert_same_tenant(assessment, tenant_id)
    return assessment


class CreateAssessmentHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: CreateAssessment) -> Assessment:
        repo = SqlAlchemyAssessmentRepository(self._session)
        tenant_id = TenantId.from_string(command.tenant_id)

        assessment, event = Assessment.create(
            tenant_id=tenant_id,
            name=command.name,
            hazard_type=HazardType(command.hazard_type),
            created_by=UserId.from_string(command.created_by),
        )
        await repo.save(assessment)
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


class MarkAssessmentReadyHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: MarkAssessmentReady) -> Assessment:
        repo = SqlAlchemyAssessmentRepository(self._session)
        tenant_id = TenantId.from_string(command.tenant_id)
        assessment = await _load_or_404(repo, command.assessment_id, tenant_id)

        event = assessment.mark_ready(changed_by=command.changed_by)
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


class StartAssessmentHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: StartAssessment) -> Assessment:
        repo = SqlAlchemyAssessmentRepository(self._session)
        tenant_id = TenantId.from_string(command.tenant_id)
        assessment = await _load_or_404(repo, command.assessment_id, tenant_id)

        event = assessment.start(changed_by=command.changed_by)
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


class ValidateAssessmentHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: ValidateAssessment) -> Assessment:
        repo = SqlAlchemyAssessmentRepository(self._session)
        tenant_id = TenantId.from_string(command.tenant_id)
        assessment = await _load_or_404(repo, command.assessment_id, tenant_id)

        event = assessment.mark_validated(changed_by=command.changed_by)
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


class ReportAssessmentHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: ReportAssessment) -> Assessment:
        repo = SqlAlchemyAssessmentRepository(self._session)
        tenant_id = TenantId.from_string(command.tenant_id)
        assessment = await _load_or_404(repo, command.assessment_id, tenant_id)

        event = assessment.mark_reported(changed_by=command.changed_by)
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


class ArchiveAssessmentHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: ArchiveAssessment) -> Assessment:
        repo = SqlAlchemyAssessmentRepository(self._session)
        tenant_id = TenantId.from_string(command.tenant_id)
        assessment = await _load_or_404(repo, command.assessment_id, tenant_id)

        event = assessment.archive(archived_by=command.archived_by)
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


class CancelAssessmentHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: CancelAssessment) -> Assessment:
        repo = SqlAlchemyAssessmentRepository(self._session)
        tenant_id = TenantId.from_string(command.tenant_id)
        assessment = await _load_or_404(repo, command.assessment_id, tenant_id)

        event = assessment.cancel(reason=command.reason, cancelled_by=command.cancelled_by)
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
