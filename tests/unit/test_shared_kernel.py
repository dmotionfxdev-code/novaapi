"""Unit tests for shared_kernel — pure logic, no I/O."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from georisk.shared_kernel.errors import DomainError, GuardRejectedError, ValidationFailedError
from georisk.shared_kernel.ids import TypedId
from georisk.shared_kernel.types import CursorPage, DateRange

pytestmark = pytest.mark.unit


class TenantIdForTest(TypedId):
    pass


class AssessmentIdForTest(TypedId):
    pass


def test_typed_id_is_generated_uniquely() -> None:
    a = TenantIdForTest.new()
    b = TenantIdForTest.new()
    assert a != b


def test_typed_id_round_trips_through_string() -> None:
    original = TenantIdForTest.new()
    reconstructed = TenantIdForTest.from_string(str(original))
    assert original == reconstructed


def test_typed_id_subclasses_are_never_equal_even_with_same_uuid() -> None:
    """The whole point of TypedId (Domain Model §3): a StageResultId must
    never be accidentally interchangeable with an AoiId, even if someone
    constructs both from the same underlying UUID value.
    """
    shared_uuid = TenantIdForTest.new().value
    tenant_id = TenantIdForTest(value=shared_uuid)
    assessment_id = AssessmentIdForTest(value=shared_uuid)

    assert tenant_id != assessment_id
    assert hash(tenant_id) != hash(assessment_id)


def test_date_range_accepts_valid_range() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=1)
    date_range = DateRange(start=start, end=end)
    assert date_range.start < date_range.end


def test_date_range_rejects_start_after_end() -> None:
    start = datetime(2026, 1, 2, tzinfo=UTC)
    end = start - timedelta(days=1)
    with pytest.raises(ValueError, match="is after end"):
        DateRange(start=start, end=end)


def test_cursor_page_holds_items_and_pagination_state() -> None:
    page: CursorPage[int] = CursorPage(items=[1, 2, 3], next_cursor="abc", has_more=True)
    assert page.items == [1, 2, 3]
    assert page.has_more is True


def test_validation_failed_error_carries_field_errors() -> None:
    exc = ValidationFailedError("bad input", field_errors=[{"field": "x", "code": "required"}])
    assert exc.field_errors[0]["field"] == "x"


def test_domain_error_hierarchy() -> None:
    assert issubclass(GuardRejectedError, DomainError)
    assert issubclass(ValidationFailedError, DomainError)
