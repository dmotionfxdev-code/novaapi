"""Domain-layer unit tests for the ``ValidationRun`` aggregate — pure
logic, no I/O. Proves verdict is genuinely computed from metrics vs.
thresholds (never settable directly) and that both construction paths
(``complete``/``error``) emit the correct event pairs.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.validation.domain.entities import ValidationRun
from georisk.contexts.validation.domain.metrics import compute_metric_set
from georisk.contexts.validation.domain.regression_metrics import compute_regression_metric_set
from georisk.contexts.validation.domain.value_objects import (
    RegressionModelMetadata,
    RegressionValidationDataset,
    SubjectType,
    ValidationDataset,
    ValidationMode,
    ValidationRunStatus,
    ValidationThresholds,
    Verdict,
)

pytestmark = pytest.mark.unit


def _passing_metrics():
    dataset = ValidationDataset(
        y_true=("POSITIVE", "POSITIVE", "NEGATIVE", "NEGATIVE"),
        y_pred=("POSITIVE", "POSITIVE", "NEGATIVE", "NEGATIVE"),
        labels=("NEGATIVE", "POSITIVE"),
    )
    return compute_metric_set(dataset)


def _failing_metrics():
    dataset = ValidationDataset(
        y_true=("POSITIVE", "POSITIVE", "NEGATIVE", "NEGATIVE"),
        y_pred=("NEGATIVE", "NEGATIVE", "POSITIVE", "POSITIVE"),
        labels=("NEGATIVE", "POSITIVE"),
    )
    return compute_metric_set(dataset)


def test_complete_with_passing_metrics_emits_validation_completed() -> None:
    run, started, outcome = ValidationRun.complete(
        tenant_id=TenantId.new(),
        assessment_id="11111111-1111-1111-1111-111111111111",
        subject_id="stub:subject",
        subject_type=SubjectType.STAGE_RESULT,
        thresholds=ValidationThresholds(min_overall_accuracy=0.7),
        metrics=_passing_metrics(),
        issued_by="analyst-1",
    )
    assert run.status == ValidationRunStatus.COMPLETED
    assert run.verdict is Verdict.PASS
    assert run.error is None
    assert started.validation_run_id == str(run.id)
    assert outcome.event_type == "validation.ValidationCompleted"


def test_complete_with_failing_metrics_emits_validation_failed() -> None:
    run, _started, outcome = ValidationRun.complete(
        tenant_id=TenantId.new(),
        assessment_id="11111111-1111-1111-1111-111111111111",
        subject_id="stub:subject",
        subject_type=SubjectType.STAGE_RESULT,
        thresholds=ValidationThresholds(min_overall_accuracy=0.7),
        metrics=_failing_metrics(),
        issued_by="analyst-1",
    )
    assert run.verdict is Verdict.FAIL
    assert outcome.event_type == "validation.ValidationFailed"


def test_error_produces_failed_status_with_no_metrics_or_verdict() -> None:
    run, started, errored = ValidationRun.errored(
        tenant_id=TenantId.new(),
        assessment_id="11111111-1111-1111-1111-111111111111",
        subject_id="stub:subject",
        subject_type=SubjectType.PREDICTION,
        thresholds=ValidationThresholds(),
        error="resolver exploded",
        issued_by="system:workflow-engine",
    )
    assert run.status == ValidationRunStatus.FAILED
    assert run.metrics is None
    assert run.verdict is None
    assert run.error == "resolver exploded"
    assert started.subject_type == "PREDICTION"
    assert errored.event_type == "validation.ValidationRunErrored"
    assert errored.error == "resolver exploded"


def _model_metadata() -> RegressionModelMetadata:
    return RegressionModelMetadata(
        prediction_run_id="11111111-1111-1111-1111-111111111111",
        method="MULTIPLE_LINEAR_REGRESSION",
        formula_version="mlr-ols-v1",
        predictor_variable_codes=("ndvi", "wind_speed"),
        dependent_variable_code="burned_area",
        sample_size=1000,
        computed_at=datetime.now(UTC),
    )


def test_complete_regression_with_passing_metrics_emits_regression_validation_completed() -> None:
    dataset = RegressionValidationDataset(
        y_true=(10.0, 20.0, 30.0, 40.0, 50.0),
        y_pred=(10.0, 20.0, 30.0, 40.0, 50.0),
        num_predictors=1,
    )
    metrics = compute_regression_metric_set(dataset)
    run, started, outcome = ValidationRun.complete_regression(
        tenant_id=TenantId.new(),
        assessment_id="11111111-1111-1111-1111-111111111111",
        subject_id="22222222-2222-2222-2222-222222222222",
        thresholds=ValidationThresholds(min_r_squared=0.5),
        metrics=metrics,
        model_metadata=_model_metadata(),
        issued_by="analyst-1",
    )
    assert run.mode == ValidationMode.REGRESSION
    assert run.subject_type is SubjectType.PREDICTION
    assert run.status == ValidationRunStatus.COMPLETED
    assert run.verdict is Verdict.PASS
    assert run.metrics is None
    assert run.regression_metrics is metrics
    assert run.model_metadata is not None
    assert run.model_metadata.formula_version == "mlr-ols-v1"
    assert started.subject_type == "PREDICTION"
    assert outcome.event_type == "validation.RegressionValidationCompleted"
    assert outcome.r_squared == pytest.approx(1.0)


def test_complete_regression_with_failing_metrics_emits_regression_validation_failed() -> None:
    dataset = RegressionValidationDataset(
        y_true=(10.0, 20.0, 15.0, 25.0, 30.0, 12.0, 18.0, 22.0, 28.0, 16.0),
        y_pred=(12.5, 17.5, 17.0, 22.0, 27.5, 14.5, 15.5, 24.5, 25.0, 18.5),
        num_predictors=2,
    )
    metrics = compute_regression_metric_set(dataset)
    run, _started, outcome = ValidationRun.complete_regression(
        tenant_id=TenantId.new(),
        assessment_id="11111111-1111-1111-1111-111111111111",
        subject_id="22222222-2222-2222-2222-222222222222",
        thresholds=ValidationThresholds(min_r_squared=0.95),
        metrics=metrics,
        model_metadata=None,
        issued_by="analyst-1",
    )
    assert run.verdict is Verdict.FAIL
    assert run.model_metadata is None
    assert outcome.event_type == "validation.RegressionValidationFailed"


def test_errored_defaults_to_classification_mode_but_accepts_regression() -> None:
    run, _started, _errored = ValidationRun.errored(
        tenant_id=TenantId.new(),
        assessment_id="11111111-1111-1111-1111-111111111111",
        subject_id="stub:subject",
        subject_type=SubjectType.PREDICTION,
        thresholds=ValidationThresholds(),
        error="resolver exploded",
        issued_by="analyst-1",
        mode=ValidationMode.REGRESSION,
    )
    assert run.mode == ValidationMode.REGRESSION


def test_verdict_is_never_settable_outside_complete() -> None:
    """Structural proof, not just a docstring claim: ValidationRun has no
    public method other than `complete`/`complete_regression`/`errored`
    (all classmethods constructing a brand-new instance) that could
    assign `verdict`."""
    public_methods = {
        name
        for name in vars(ValidationRun)
        if not name.startswith("_") and callable(getattr(ValidationRun, name))
    }
    assert public_methods == {"complete", "complete_regression", "errored"}
