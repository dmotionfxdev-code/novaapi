"""Validation domain events — appended to the outbox within the same
transaction as the `ValidationRun` they describe (Sprint 4 brief's
"Validation only emits events" requirement, satisfied by the identical
mechanism proven in every prior sprint). `ValidationCompleted` (verdict
PASS) and `ValidationFailed` (verdict FAIL) are two distinct event types,
not one generic event with a verdict field — matching the Application
Layer §12 worked trace exactly ("outbox: ValidationCompleted (verdict=PASS)
or ValidationFailed"), since downstream subscribers (Notification, a future
Report gate) care about *which one fired*, not about parsing a payload
field. `ValidationRunErrored` is this module's own addition, for the
distinct case the worked trace doesn't cover: the computation itself
failing (bad input, resolver exception) — orthogonal to a subject failing
its quality bar.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class ValidationRunStarted:
    event_type: ClassVar[str] = "validation.ValidationRunStarted"
    validation_run_id: str
    tenant_id: str
    assessment_id: str
    subject_id: str
    subject_type: str
    issued_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class ValidationCompleted:
    event_type: ClassVar[str] = "validation.ValidationCompleted"
    validation_run_id: str
    tenant_id: str
    assessment_id: str
    overall_accuracy: float | None
    f1_score: float | None
    auc: float | None

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class ValidationFailed:
    event_type: ClassVar[str] = "validation.ValidationFailed"
    validation_run_id: str
    tenant_id: str
    assessment_id: str
    overall_accuracy: float | None
    f1_score: float | None
    auc: float | None

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class RegressionValidationCompleted:
    """Sprint 10 requirement #7 — the regression-mode counterpart of
    ``ValidationCompleted``, a distinct event type (not a generic event
    with a ``mode`` field) so a downstream subscriber can tell which
    metric shape the payload carries without inspecting it — the same
    reasoning this module's own docstring already gives for
    ``ValidationCompleted``/``ValidationFailed`` being two types.
    """

    event_type: ClassVar[str] = "validation.RegressionValidationCompleted"
    validation_run_id: str
    tenant_id: str
    assessment_id: str
    rmse: float
    mae: float
    r_squared: float
    adjusted_r_squared: float

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class RegressionValidationFailed:
    event_type: ClassVar[str] = "validation.RegressionValidationFailed"
    validation_run_id: str
    tenant_id: str
    assessment_id: str
    rmse: float
    mae: float
    r_squared: float
    adjusted_r_squared: float

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class ValidationRunErrored:
    event_type: ClassVar[str] = "validation.ValidationRunErrored"
    validation_run_id: str
    tenant_id: str
    assessment_id: str
    error: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}
