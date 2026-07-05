"""Command DTO (Application Layer §1). Named exactly as Domain Model §1 row
14 / Application Layer's Validation command table specify:
``RunValidation { assessmentId, subjectId, subjectType }`` — issued by
"System (Workflow Engine, reacting to ...)" or "User (ad hoc
re-validation)" (Application Layer, Validation command table); the
``issued_by`` field carries whichever actor string the caller used
(``system:workflow-engine`` or a real user id), matching how every other
context in this codebase already distinguishes system vs. user actors.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RunValidationCommand:
    tenant_id: str
    assessment_id: str
    subject_id: str
    subject_type: str
    issued_by: str


@dataclass(frozen=True, slots=True)
class RunRegressionValidationCommand:
    """Sprint 10's regression-mode counterpart of ``RunValidationCommand``.
    ``subject_type`` isn't a parameter — regression validation only ever
    judges a Prediction context model fit (``SubjectType.PREDICTION``,
    fixed inside ``ValidationRun.complete_regression()``), so there's
    nothing for a caller to choose."""

    tenant_id: str
    assessment_id: str
    subject_id: str
    issued_by: str
