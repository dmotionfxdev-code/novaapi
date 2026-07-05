"""Unit tests for the Dashboard aggregation kernel
(`contexts.dashboard.domain.aggregation`) — pure computation, no I/O.
Sprint 12's own "Dashboard aggregation tests" validation requirement is
satisfied directly by this file: every dashboard query handler composes
its KPIs/summary cards/trend from these functions, so testing them in
isolation covers the actual aggregation logic every dashboard depends on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from georisk.contexts.dashboard.domain.aggregation import average, build_trend, count_by, rate

pytestmark = pytest.mark.unit


def test_count_by_groups_and_counts() -> None:
    items = ["FLOOD", "WILDFIRE", "FLOOD", "FLOOD", "WILDFIRE"]
    assert count_by(items, lambda x: x) == {"FLOOD": 3, "WILDFIRE": 2}


def test_count_by_empty_sequence_returns_empty_dict() -> None:
    assert count_by([], lambda x: x) == {}


def test_average_of_values() -> None:
    assert average([1.0, 2.0, 3.0]) == pytest.approx(2.0)


def test_average_of_empty_sequence_is_none_not_zero() -> None:
    """An empty input means "no data yet," not "the average is 0.0" —
    these are different facts a dashboard should render differently."""
    assert average([]) is None


def test_rate_computes_ratio() -> None:
    assert rate(3, 4) == pytest.approx(0.75)


def test_rate_with_zero_denominator_is_zero_not_an_error() -> None:
    assert rate(0, 0) == 0.0


@dataclass
class _FakeItem:
    label: str
    value: float
    occurred_at: datetime


def test_build_trend_sorts_chronologically_regardless_of_input_order() -> None:
    now = datetime.now(UTC)
    items = [
        _FakeItem("third", 3.0, now + timedelta(days=2)),
        _FakeItem("first", 1.0, now),
        _FakeItem("second", 2.0, now + timedelta(days=1)),
    ]
    trend = build_trend(
        items, label=lambda i: i.label, value=lambda i: i.value, occurred_at=lambda i: i.occurred_at
    )
    assert [p.label for p in trend] == ["first", "second", "third"]
    assert [p.value for p in trend] == [1.0, 2.0, 3.0]


def test_build_trend_of_empty_sequence_is_empty_tuple() -> None:
    trend = build_trend(
        [], label=lambda i: i.label, value=lambda i: i.value, occurred_at=lambda i: i.occurred_at
    )
    assert trend == ()
