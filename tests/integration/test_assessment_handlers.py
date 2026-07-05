"""Handler-level integration tests — the cross-cutting concerns domain unit
tests can't exercise: tenant isolation enforcement and outbox event
emission against a real database.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from georisk.contexts.assessment.application.commands import (
    ArchiveAssessment,
    CancelAssessment,
    CreateAssessment,
    MarkAssessmentReady,
    ReportAssessment,
    StartAssessment,
    ValidateAssessment,
)
from georisk.contexts.assessment.application.handlers import (
    ArchiveAssessmentHandler,
    CancelAssessmentHandler,
    CreateAssessmentHandler,
    MarkAssessmentReadyHandler,
    ReportAssessmentHandler,
    StartAssessmentHandler,
    ValidateAssessmentHandler,
)
from georisk.contexts.assessment.domain.errors import AssessmentNotFoundError
from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.db.outbox_models import OutboxEventModel

pytestmark = pytest.mark.integration


async def test_create_assessment_appends_outbox_event(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    handler = CreateAssessmentHandler(db_session)
    assessment = await handler.handle(
        CreateAssessment(
            tenant_id=str(tenant_id),
            name=f"Outbox Test {uuid.uuid4().hex[:8]}",
            hazard_type="FLOOD",
            created_by=str(UserId.new()),
        )
    )

    result = await db_session.execute(
        select(OutboxEventModel).where(
            OutboxEventModel.aggregate_type == "Assessment",
            OutboxEventModel.aggregate_id == str(assessment.id),
        )
    )
    events = result.scalars().all()
    assert len(events) == 1
    assert events[0].event_type == "assessment.AssessmentCreated"
    assert events[0].tenant_id == tenant_id.value


async def test_full_lifecycle_through_handlers_emits_correct_event_sequence(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    actor = str(UserId.new())

    assessment = await CreateAssessmentHandler(db_session).handle(
        CreateAssessment(
            tenant_id=str(tenant_id),
            name="Lifecycle Test",
            hazard_type="WILDFIRE",
            created_by=actor,
        )
    )
    assessment_id = str(assessment.id)

    await MarkAssessmentReadyHandler(db_session).handle(
        MarkAssessmentReady(tenant_id=str(tenant_id), assessment_id=assessment_id, changed_by=actor)
    )
    await StartAssessmentHandler(db_session).handle(
        StartAssessment(tenant_id=str(tenant_id), assessment_id=assessment_id, changed_by=actor)
    )
    await ValidateAssessmentHandler(db_session).handle(
        ValidateAssessment(tenant_id=str(tenant_id), assessment_id=assessment_id, changed_by=actor)
    )
    await ReportAssessmentHandler(db_session).handle(
        ReportAssessment(tenant_id=str(tenant_id), assessment_id=assessment_id, changed_by=actor)
    )
    final = await ArchiveAssessmentHandler(db_session).handle(
        ArchiveAssessment(tenant_id=str(tenant_id), assessment_id=assessment_id, archived_by=actor)
    )
    assert final.status.value == "ARCHIVED"

    result = await db_session.execute(
        select(OutboxEventModel)
        .where(
            OutboxEventModel.aggregate_type == "Assessment",
            OutboxEventModel.aggregate_id == assessment_id,
        )
        .order_by(OutboxEventModel.sequence_number)
    )
    events = result.scalars().all()
    event_types = [e.event_type for e in events]
    assert event_types == [
        "assessment.AssessmentCreated",
        "assessment.AssessmentStageAdvanced",  # DRAFT -> READY
        "assessment.AssessmentStageAdvanced",  # READY -> RUNNING
        "assessment.AssessmentStageAdvanced",  # RUNNING -> VALIDATED
        "assessment.AssessmentStageAdvanced",  # VALIDATED -> REPORTED
        "assessment.AssessmentArchived",
    ]
    assert [e.sequence_number for e in events] == list(range(1, len(events) + 1))


async def test_cancel_from_running_emits_cancelled_event(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    actor = str(UserId.new())

    assessment = await CreateAssessmentHandler(db_session).handle(
        CreateAssessment(
            tenant_id=str(tenant_id), name="Cancel Test", hazard_type="LANDSLIDE", created_by=actor
        )
    )
    assessment_id = str(assessment.id)
    await MarkAssessmentReadyHandler(db_session).handle(
        MarkAssessmentReady(tenant_id=str(tenant_id), assessment_id=assessment_id, changed_by=actor)
    )
    await StartAssessmentHandler(db_session).handle(
        StartAssessment(tenant_id=str(tenant_id), assessment_id=assessment_id, changed_by=actor)
    )
    cancelled = await CancelAssessmentHandler(db_session).handle(
        CancelAssessment(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            reason="scope changed",
            cancelled_by=actor,
        )
    )
    assert cancelled.status.value == "CANCELLED"
    assert cancelled.cancellation_reason == "scope changed"


async def test_cross_tenant_access_is_reported_as_not_found(db_session) -> None:  # noqa: ANN001
    """Interim, application-layer tenant scoping (Roadmap Sprint 1/2) —
    an actor from tenant B must not be able to act on, or even discover
    the existence of, an assessment belonging to tenant A.
    """
    tenant_a = TenantId.new()
    tenant_b = TenantId.new()
    actor_a = str(UserId.new())
    actor_b = str(UserId.new())

    assessment = await CreateAssessmentHandler(db_session).handle(
        CreateAssessment(
            tenant_id=str(tenant_a), name="Tenant A Only", hazard_type="FLOOD", created_by=actor_a
        )
    )

    with pytest.raises(AssessmentNotFoundError):
        await MarkAssessmentReadyHandler(db_session).handle(
            MarkAssessmentReady(
                tenant_id=str(tenant_b), assessment_id=str(assessment.id), changed_by=actor_b
            )
        )
