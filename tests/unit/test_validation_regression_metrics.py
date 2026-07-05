"""Unit tests for the regression validation metrics kernel
(`contexts.validation.domain.regression_metrics`) — pure computation, no
I/O. Reference values computed by directly running the ported functions
and pinned here so any future change to the formulas is a deliberate,
visible diff (same discipline as Prediction's own MLR/correlation unit
tests, Sprint 8).
"""

from __future__ import annotations

import pytest

from georisk.contexts.validation.domain.regression_metrics import (
    compute_regression_metric_set,
    compute_regression_verdict,
)
from georisk.contexts.validation.domain.value_objects import (
    RegressionValidationDataset,
    ValidationThresholds,
    Verdict,
)

pytestmark = pytest.mark.unit


def test_compute_regression_metric_set_perfect_fit_is_zero_error_full_r_squared() -> None:
    dataset = RegressionValidationDataset(
        y_true=(10.0, 20.0, 30.0, 40.0, 50.0),
        y_pred=(10.0, 20.0, 30.0, 40.0, 50.0),
        num_predictors=1,
    )
    metrics = compute_regression_metric_set(dataset)
    assert metrics.rmse == pytest.approx(0.0)
    assert metrics.mae == pytest.approx(0.0)
    assert metrics.mse == pytest.approx(0.0)
    assert metrics.r_squared == pytest.approx(1.0)
    assert metrics.adjusted_r_squared == pytest.approx(1.0)
    assert metrics.sample_size == 5


def test_compute_regression_metric_set_matches_hand_computed_reference() -> None:
    dataset = RegressionValidationDataset(
        y_true=(10.0, 20.0, 15.0, 25.0, 30.0, 12.0, 18.0, 22.0, 28.0, 16.0),
        y_pred=(12.5, 17.5, 17.0, 22.0, 27.5, 14.5, 15.5, 24.5, 25.0, 18.5),
        num_predictors=2,
    )
    metrics = compute_regression_metric_set(dataset)
    assert metrics.mse == pytest.approx(6.575)
    assert metrics.rmse == pytest.approx(2.564176, abs=1e-5)
    assert metrics.mae == pytest.approx(2.55)
    assert metrics.r_squared == pytest.approx(0.835789, abs=1e-5)
    assert metrics.adjusted_r_squared == pytest.approx(0.788872, abs=1e-5)


def test_compute_regression_metric_set_zero_variance_y_true_is_zero_r_squared() -> None:
    dataset = RegressionValidationDataset(
        y_true=(5.0, 5.0, 5.0),
        y_pred=(4.0, 5.0, 6.0),
        num_predictors=1,
    )
    metrics = compute_regression_metric_set(dataset)
    assert metrics.r_squared == 0.0


def test_regression_validation_dataset_requires_at_least_two_samples() -> None:
    with pytest.raises(ValueError, match="at least 2 samples"):
        RegressionValidationDataset(y_true=(1.0,), y_pred=(1.0,), num_predictors=1)


def test_regression_validation_dataset_requires_matching_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        RegressionValidationDataset(y_true=(1.0, 2.0), y_pred=(1.0,), num_predictors=1)


def test_compute_regression_verdict_passes_when_no_thresholds_declared() -> None:
    dataset = RegressionValidationDataset(
        y_true=(1.0, 100.0, 2.0), y_pred=(50.0, 1.0, 90.0), num_predictors=1
    )
    metrics = compute_regression_metric_set(dataset)
    assert compute_regression_verdict(metrics, ValidationThresholds()) is Verdict.PASS


def test_compute_regression_verdict_fails_closed_on_rmse_upper_bound() -> None:
    dataset = RegressionValidationDataset(
        y_true=(10.0, 20.0, 15.0, 25.0, 30.0, 12.0, 18.0, 22.0, 28.0, 16.0),
        y_pred=(12.5, 17.5, 17.0, 22.0, 27.5, 14.5, 15.5, 24.5, 25.0, 18.5),
        num_predictors=2,
    )
    metrics = compute_regression_metric_set(dataset)
    assert compute_regression_verdict(metrics, ValidationThresholds(max_rmse=1.0)) is Verdict.FAIL
    assert compute_regression_verdict(metrics, ValidationThresholds(max_rmse=5.0)) is Verdict.PASS


def test_compute_regression_verdict_fails_closed_on_r_squared_lower_bound() -> None:
    dataset = RegressionValidationDataset(
        y_true=(10.0, 20.0, 15.0, 25.0, 30.0, 12.0, 18.0, 22.0, 28.0, 16.0),
        y_pred=(12.5, 17.5, 17.0, 22.0, 27.5, 14.5, 15.5, 24.5, 25.0, 18.5),
        num_predictors=2,
    )
    metrics = compute_regression_metric_set(dataset)
    assert (
        compute_regression_verdict(metrics, ValidationThresholds(min_r_squared=0.95))
        is Verdict.FAIL
    )
    assert (
        compute_regression_verdict(metrics, ValidationThresholds(min_r_squared=0.5))
        is Verdict.PASS
    )
