"""Generic value types with no hazard- or context-specific meaning.

Kept deliberately small in Sprint 0 — anything with domain meaning
(``ConfidenceTier``, ``Geometry``, ``HazardType``, ...) belongs to the
bounded context that defines it once that context's sprint lands, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class DateRange:
    """A validated, inclusive start/end range. Used across every context
    that deals in time-bounded data (acquisition jobs, sensor windows,
    report periods) — genuinely context-agnostic.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"DateRange start ({self.start}) is after end ({self.end})")


@dataclass(frozen=True, slots=True)
class CursorPage(Generic[T]):
    """Generic cursor-paginated result envelope (API Resource Model §6) —
    every list query handler returns one of these, regardless of context.
    """

    items: list[T]
    next_cursor: str | None
    has_more: bool
