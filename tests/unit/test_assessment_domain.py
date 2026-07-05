"""Domain-layer unit tests for Assessment — pure logic, no I/O. Exercises
every legal transition in ``value_objects.LEGAL_TRANSITIONS`` and a
representative sample of illegal ones, proving the FSM is actually
enforced by the entity, not just documented.
"""

from __future__ import annotations

import pytest

from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.errors import IllegalAssessmentStatusTransitionError
from georisk.contexts.assessment.domain.value_objects import (
    LEGAL_TRANSITIONS,
    AssessmentStatus,
    HazardType,
)
from georisk.contexts.identity.domain.value_objects import TenantId, UserId

pytestmark = pytest.mark.unit


def _new_assessment() -> Assessment:
    assessment, _ = Assessment.create(
        tenant_id=TenantId.new(),
        name="Kigoma District Q3",
        hazard_type=HazardType.FLOOD,
        created_by=UserId.new(),
    )
    return assessment


def test_create_produces_draft_assessment_and_event() -> None:
    assessment, event = Assessment.create(
        tenant_id=TenantId.new(),
        name="Test Assessment",
        hazard_type=HazardType.WILDFIRE,
        created_by=UserId.new(),
    )
    assert assessment.status == AssessmentStatus.DRAFT
    assert assessment.hazard_type == HazardType.WILDFIRE
    assert event.assessment_id == str(assessment.id)
    assert event.hazard_type == "WILDFIRE"


def test_create_rejects_blank_name() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        Assessment.create(
            tenant_id=TenantId.new(),
            name="   ",
            hazard_type=HazardType.FLOOD,
            created_by=UserId.new(),
        )


def test_full_happy_path_lifecycle() -> None:
    assessment = _new_assessment()

    event1 = assessment.mark_ready(changed_by="analyst-1")
    assert assessment.status == AssessmentStatus.READY
    assert event1.from_status == "DRAFT"
    assert event1.to_status == "READY"

    event2 = assessment.start(changed_by="analyst-1")
    assert assessment.status == AssessmentStatus.RUNNING
    assert event2.from_status == "READY"
    assert event2.to_status == "RUNNING"

    assessment.mark_validated(changed_by="analyst-1")
    assert assessment.status == AssessmentStatus.VALIDATED

    assessment.mark_reported(changed_by="analyst-1")
    assert assessment.status == AssessmentStatus.REPORTED

    event5 = assessment.archive(archived_by="analyst-1")
    assert assessment.status == AssessmentStatus.ARCHIVED
    assert event5.archived_by == "analyst-1"

    assert assessment.is_terminal() is True


@pytest.mark.parametrize(
    "from_status",
    [
        AssessmentStatus.DRAFT,
        AssessmentStatus.READY,
        AssessmentStatus.RUNNING,
        AssessmentStatus.VALIDATED,
    ],
)
def test_cancel_is_legal_from_every_non_terminal_pre_reported_state(
    from_status: AssessmentStatus,
) -> None:
    assessment = _new_assessment()
    assessment.status = from_status  # test setup shortcut — plain mutable dataclass

    event = assessment.cancel(reason="requirements changed", cancelled_by="owner-1")
    assert assessment.status == AssessmentStatus.CANCELLED
    assert assessment.cancellation_reason == "requirements changed"
    assert event.reason == "requirements changed"
    assert assessment.is_terminal() is True


def test_cancel_is_illegal_once_reported() -> None:
    assessment = _new_assessment()
    assessment.status = AssessmentStatus.REPORTED
    with pytest.raises(IllegalAssessmentStatusTransitionError):
        assessment.cancel(reason="too late", cancelled_by="owner-1")


def test_cancel_is_illegal_once_archived() -> None:
    assessment = _new_assessment()
    assessment.status = AssessmentStatus.ARCHIVED
    with pytest.raises(IllegalAssessmentStatusTransitionError):
        assessment.cancel(reason="too late", cancelled_by="owner-1")


def test_cancel_requires_a_non_blank_reason() -> None:
    assessment = _new_assessment()
    with pytest.raises(ValueError, match="reason is required"):
        assessment.cancel(reason="   ", cancelled_by="owner-1")


def test_archive_is_illegal_before_reported() -> None:
    assessment = _new_assessment()
    for status in (
        AssessmentStatus.DRAFT,
        AssessmentStatus.READY,
        AssessmentStatus.RUNNING,
        AssessmentStatus.VALIDATED,
    ):
        assessment.status = status
        with pytest.raises(IllegalAssessmentStatusTransitionError):
            assessment.archive(archived_by="owner-1")


def test_cannot_skip_states() -> None:
    """DRAFT cannot jump straight to RUNNING, VALIDATED, REPORTED, or
    ARCHIVED — only to READY (or CANCELLED)."""
    assessment = _new_assessment()
    with pytest.raises(IllegalAssessmentStatusTransitionError):
        assessment.start(changed_by="analyst-1")
    with pytest.raises(IllegalAssessmentStatusTransitionError):
        assessment.mark_validated(changed_by="analyst-1")
    with pytest.raises(IllegalAssessmentStatusTransitionError):
        assessment.mark_reported(changed_by="analyst-1")
    with pytest.raises(IllegalAssessmentStatusTransitionError):
        assessment.archive(archived_by="analyst-1")


def test_terminal_states_accept_no_further_transitions() -> None:
    for terminal in (AssessmentStatus.ARCHIVED, AssessmentStatus.CANCELLED):
        assert LEGAL_TRANSITIONS[terminal] == frozenset()


def test_every_status_is_represented_in_the_transition_table() -> None:
    assert set(LEGAL_TRANSITIONS.keys()) == set(AssessmentStatus)
