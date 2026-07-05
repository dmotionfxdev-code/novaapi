"""Domain errors for the Reporting context — subclass the shared_kernel
hierarchy, self-contained around the shared base classes (Sprint 1's
established pattern).
"""

from __future__ import annotations

from georisk.shared_kernel.errors import (
    IllegalStateTransitionError,
    NotFoundError,
    ValidationFailedError,
)


class ReportNotFoundError(NotFoundError):
    pass


class AssessmentNotAvailableError(ValidationFailedError):
    """Raised when the assessment a report is being generated for doesn't
    exist (or isn't visible to the requesting tenant) — the one mandatory
    prerequisite for report generation. Every other section (risk summary,
    prediction, validation, dataset provenance) is best-effort/optional —
    their absence produces an empty section, never a failed report."""


class IllegalReportStatusTransitionError(IllegalStateTransitionError):
    """Raised by ``Report.finalize()`` when called on a report that isn't
    currently ``DRAFT`` — "Immutable finalized reports" made structural."""
