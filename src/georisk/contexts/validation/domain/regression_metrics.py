"""Pure computation — no I/O, no ORM, no aggregate state. Sprint 10's
regression counterpart of ``metrics.py``: RMSE, MAE, MSE, R², Adjusted R²,
computed fresh from a ``RegressionValidationDataset`` (Sprint 10
requirement #2 — "Add Regression Metrics"), plus ``compute_regression_verdict``,
the regression-mode counterpart of ``metrics.compute_verdict``. Kept in its
own module rather than added to ``metrics.py`` — the same "keep
classification/regression math cleanly separated" reasoning Prediction's
``domain/correlation.py``/``domain/regression.py`` split already
established in Sprint 8.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from georisk.contexts.validation.domain.value_objects import (
    RegressionMetricSet,
    RegressionValidationDataset,
    ValidationThresholds,
    Verdict,
)

# Mirrors DEFAULT_VALIDATION_THRESHOLDS's role for classification — applied
# whenever a RunRegressionValidation command doesn't declare its own
# thresholds. R² >= 0.5 / RMSE and MAE loosely bounded is a reasonable,
# documented default gate, not a claim about any specific model's expected
# performance.
DEFAULT_REGRESSION_VALIDATION_THRESHOLDS = ValidationThresholds(
    min_r_squared=0.5,
    max_rmse=10.0,
)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_regression_metric_set(dataset: RegressionValidationDataset) -> RegressionMetricSet:
    """The single entry point ``application/handlers.py``'s regression path
    calls: one ``RegressionValidationDataset`` in, one fully-populated
    ``RegressionMetricSet`` out — mirrors ``metrics.compute_metric_set``'s
    role for classification exactly.
    """
    n = len(dataset.y_true)
    residuals = [dataset.y_true[i] - dataset.y_pred[i] for i in range(n)]

    mse = _mean([r**2 for r in residuals])
    rmse = math.sqrt(mse)
    mae = _mean([abs(r) for r in residuals])

    y_mean = _mean(dataset.y_true)
    ss_res = sum(r**2 for r in residuals)
    ss_tot = sum((y - y_mean) ** 2 for y in dataset.y_true)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    k = dataset.num_predictors
    adjusted_r_squared = (
        1.0 - (1.0 - r_squared) * (n - 1) / (n - k - 1) if n > k + 1 else 0.0
    )

    return RegressionMetricSet(
        sample_size=n,
        rmse=round(rmse, 6),
        mae=round(mae, 6),
        mse=round(mse, 6),
        r_squared=round(r_squared, 6),
        adjusted_r_squared=round(adjusted_r_squared, 6),
    )


def compute_regression_verdict(
    metrics: RegressionMetricSet, thresholds: ValidationThresholds
) -> Verdict:
    """"Verdict is a pure function of metrics vs. declared thresholds"
    (Domain Model §1 row 14), applied to regression metrics — the
    regression-mode counterpart of ``metrics.compute_verdict``, same
    "unset threshold = not checked, fails closed" rules. ``max_rmse``/
    ``max_mae`` are upper bounds (lower is better); ``min_r_squared``/
    ``min_adjusted_r_squared`` are lower bounds (higher is better).
    """
    upper_bound_checks = (
        (thresholds.max_rmse, metrics.rmse),
        (thresholds.max_mae, metrics.mae),
    )
    for threshold, value in upper_bound_checks:
        if threshold is not None and value > threshold:
            return Verdict.FAIL

    lower_bound_checks = (
        (thresholds.min_r_squared, metrics.r_squared),
        (thresholds.min_adjusted_r_squared, metrics.adjusted_r_squared),
    )
    for threshold, value in lower_bound_checks:
        if threshold is not None and value < threshold:
            return Verdict.FAIL

    return Verdict.PASS
