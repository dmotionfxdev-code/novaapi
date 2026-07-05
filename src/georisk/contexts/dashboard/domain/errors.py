"""Dashboard-specific domain errors — subclass the shared_kernel
hierarchy, self-contained around the shared base classes (Sprint 1's
established pattern).
"""

from __future__ import annotations

from georisk.shared_kernel.errors import ValidationFailedError


class AssessmentNotAvailableError(ValidationFailedError):
    """Raised when the assessment a workspace projection is requested for
    doesn't exist (or isn't visible to the requesting tenant) — the one
    hard failure mode a read-only projection has; every other section is
    best-effort/optional, mirroring Reporting's exact "one mandatory
    prerequisite, everything else degrades to empty" discipline.
    """
