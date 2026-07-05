"""Pure computation — no I/O, no ORM, nothing context-specific. Every
dashboard query handler in ``application/queries.py`` builds its
``KpiWidget``/``SummaryCard``/``TrendPoint`` tuples by calling these
functions, never by hand-rolling the same counting/averaging logic
per dashboard. Kept genuinely generic (operates on plain
``Sequence``/callables, not any domain type) so it's trivially unit-
testable in isolation — "Dashboard aggregation tests" (Sprint 12's own
validation requirement) exercises this module directly.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TypeVar

from georisk.contexts.dashboard.domain.value_objects import TrendPoint

T = TypeVar("T")


def count_by(items: Sequence[T], key: Callable[[T], str]) -> dict[str, int]:
    """Group-and-count — e.g. assessments by status, notifications by
    severity. Deterministic key order (insertion order of first
    occurrence), never sorted alphabetically, so a caller can control
    display order by controlling ``items``' order if it wants to."""
    counts: dict[str, int] = {}
    for item in items:
        k = key(item)
        counts[k] = counts.get(k, 0) + 1
    return counts


def average(values: Sequence[float]) -> float | None:
    """``None`` (not 0.0) when ``values`` is empty — "no data yet" and
    "the average is genuinely zero" are different facts, and a KPI widget
    showing "0.0" for a metric with zero observations would be
    misleading."""
    if not values:
        return None
    return sum(values) / len(values)


def rate(numerator: int, denominator: int) -> float:
    """A ``0.0``-safe ratio (e.g. pass rate, MLR-ready ratio) — an empty
    denominator means "nothing to compute a rate from yet," which is
    honestly ``0.0``, not an error or a ``None``: a dashboard showing a
    fresh tenant's 0-of-0 pass rate as "0%" is more useful than a widget
    that has to special-case rendering ``None``.
    """
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def build_trend(
    items: Sequence[T],
    *,
    label: Callable[[T], str],
    value: Callable[[T], float],
    occurred_at: Callable[[T], datetime],
) -> tuple[TrendPoint, ...]:
    """Sorts ``items`` chronologically by ``occurred_at`` before mapping
    to ``TrendPoint`` — the caller's own list order (e.g. "newest-first"
    repository results) is never assumed to already be a valid trend
    order."""
    ordered = sorted(items, key=occurred_at)
    return tuple(
        TrendPoint(label=label(i), value=value(i), occurred_at=occurred_at(i)) for i in ordered
    )
