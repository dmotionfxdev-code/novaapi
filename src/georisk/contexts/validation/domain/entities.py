"""The `ValidationRun` aggregate (Domain Model §1 row 14) — the Validation
context's sole aggregate root. "A validation run judges predicted-vs-
observed with standard statistics — it has no opinion about floods, only
about numbers" (Domain Model §4): nothing here references a hazard type,
an assessment's internal fields, or a GIS concept, and nothing here imports
from `contexts.assessment` — structurally enforced by the import-linter's
peer-independence contract, not just a convention.

Both classmethods are one-shot: metric computation (`metrics.py`) is
synchronous, pure-Python math with no async job in between "asked to run"
and "done", so there is no separate PENDING→RUNNING transition to model —
see `value_objects.ValidationRunStatus`'s docstring. `verdict` is never
settable except as `metrics.compute_verdict`'s return value, computed
inside `complete()` — there is no method on this class that assigns it
directly, the same "no direct mutation" structural guarantee every prior
sprint's aggregates enforce for their own state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.validation.domain.events import (
    RegressionValidationCompleted,
    RegressionValidationFailed,
    ValidationCompleted,
    ValidationFailed,
    ValidationRunErrored,
    ValidationRunStarted,
)
from georisk.contexts.validation.domain.metrics import compute_verdict
from georisk.contexts.validation.domain.regression_metrics import compute_regression_verdict
from georisk.contexts.validation.domain.value_objects import (
    MetricSet,
    RegressionMetricSet,
    RegressionModelMetadata,
    SubjectType,
    ValidationMode,
    ValidationRunId,
    ValidationRunStatus,
    ValidationThresholds,
    Verdict,
)


@dataclass(slots=True)
class ValidationRun:
    id: ValidationRunId
    tenant_id: TenantId
    # Soft, plain-string cross-context references — see value_objects.py's
    # module docstring for why these are never typed ids imported from
    # another context.
    assessment_id: str
    subject_id: str
    subject_type: SubjectType
    mode: ValidationMode
    status: ValidationRunStatus
    thresholds: ValidationThresholds
    metrics: MetricSet | None
    verdict: Verdict | None
    error: str | None
    issued_by: str
    created_at: datetime
    # Sprint 10: populated instead of ``metrics`` when ``mode`` is
    # ``REGRESSION`` — mutually exclusive with ``metrics``, the same
    # "either/or, never both" pattern ``PredictionRun.correlation_result``/
    # ``regression_result`` established in Sprint 8.
    regression_metrics: RegressionMetricSet | None = None
    model_metadata: RegressionModelMetadata | None = None
    version: int = field(default=0)

    @classmethod
    def complete(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        subject_id: str,
        subject_type: SubjectType,
        thresholds: ValidationThresholds,
        metrics: MetricSet,
        issued_by: str,
    ) -> tuple[ValidationRun, ValidationRunStarted, ValidationCompleted | ValidationFailed]:
        verdict = compute_verdict(metrics, thresholds)
        run = cls(
            id=ValidationRunId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            subject_id=subject_id,
            subject_type=subject_type,
            mode=ValidationMode.CLASSIFICATION,
            status=ValidationRunStatus.COMPLETED,
            thresholds=thresholds,
            metrics=metrics,
            verdict=verdict,
            error=None,
            issued_by=issued_by,
            created_at=datetime.now(UTC),
        )
        started = ValidationRunStarted(
            validation_run_id=str(run.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            subject_id=subject_id,
            subject_type=subject_type.value,
            issued_by=issued_by,
        )
        outcome: ValidationCompleted | ValidationFailed
        if verdict is Verdict.PASS:
            outcome = ValidationCompleted(
                validation_run_id=str(run.id),
                tenant_id=str(tenant_id),
                assessment_id=assessment_id,
                overall_accuracy=metrics.overall_accuracy,
                f1_score=metrics.f1_score,
                auc=metrics.auc,
            )
        else:
            outcome = ValidationFailed(
                validation_run_id=str(run.id),
                tenant_id=str(tenant_id),
                assessment_id=assessment_id,
                overall_accuracy=metrics.overall_accuracy,
                f1_score=metrics.f1_score,
                auc=metrics.auc,
            )
        return run, started, outcome

    @classmethod
    def complete_regression(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        subject_id: str,
        thresholds: ValidationThresholds,
        metrics: RegressionMetricSet,
        model_metadata: RegressionModelMetadata | None,
        issued_by: str,
    ) -> tuple[
        ValidationRun,
        ValidationRunStarted,
        RegressionValidationCompleted | RegressionValidationFailed,
    ]:
        """Sprint 10's regression-mode counterpart of ``complete()``.
        ``subject_type`` is always ``PREDICTION`` — regression validation
        only ever judges a Prediction context model fit, unlike
        classification's ``STAGE_RESULT``/``PREDICTION`` either/or, so it's
        fixed here rather than taken as a parameter.
        """
        verdict = compute_regression_verdict(metrics, thresholds)
        run = cls(
            id=ValidationRunId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            subject_id=subject_id,
            subject_type=SubjectType.PREDICTION,
            mode=ValidationMode.REGRESSION,
            status=ValidationRunStatus.COMPLETED,
            thresholds=thresholds,
            metrics=None,
            verdict=verdict,
            error=None,
            issued_by=issued_by,
            created_at=datetime.now(UTC),
            regression_metrics=metrics,
            model_metadata=model_metadata,
        )
        started = ValidationRunStarted(
            validation_run_id=str(run.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            subject_id=subject_id,
            subject_type=SubjectType.PREDICTION.value,
            issued_by=issued_by,
        )
        outcome: RegressionValidationCompleted | RegressionValidationFailed
        outcome_cls = (
            RegressionValidationCompleted if verdict is Verdict.PASS else RegressionValidationFailed
        )
        outcome = outcome_cls(
            validation_run_id=str(run.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            rmse=metrics.rmse,
            mae=metrics.mae,
            r_squared=metrics.r_squared,
            adjusted_r_squared=metrics.adjusted_r_squared,
        )
        return run, started, outcome

    @classmethod
    def errored(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        subject_id: str,
        subject_type: SubjectType,
        thresholds: ValidationThresholds,
        error: str,
        issued_by: str,
        mode: ValidationMode = ValidationMode.CLASSIFICATION,
    ) -> tuple[ValidationRun, ValidationRunStarted, ValidationRunErrored]:
        run = cls(
            id=ValidationRunId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            subject_id=subject_id,
            subject_type=subject_type,
            mode=mode,
            status=ValidationRunStatus.FAILED,
            thresholds=thresholds,
            metrics=None,
            verdict=None,
            error=error,
            issued_by=issued_by,
            created_at=datetime.now(UTC),
        )
        started = ValidationRunStarted(
            validation_run_id=str(run.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            subject_id=subject_id,
            subject_type=subject_type.value,
            issued_by=issued_by,
        )
        errored = ValidationRunErrored(
            validation_run_id=str(run.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            error=error,
        )
        return run, started, errored
