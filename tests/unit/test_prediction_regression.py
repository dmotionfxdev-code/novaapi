"""Unit tests for the Multiple Linear Regression Engine — pure
computation, no I/O. Reference values computed by directly running the
ported function against a noise-free synthetic dataset with a known true
relationship (``y = 2*x1 + 3*x2 + 5``), which OLS must recover exactly.
"""

from __future__ import annotations

import pytest

from georisk.contexts.prediction.domain.errors import InsufficientObservationsError
from georisk.contexts.prediction.domain.regression import compute_multiple_linear_regression

pytestmark = pytest.mark.unit

_FEATURE_MATRIX = [
    [1.0, 2.0],
    [2.0, 1.0],
    [3.0, 3.0],
    [4.0, 2.0],
    [5.0, 4.0],
    [6.0, 1.0],
    [2.0, 5.0],
    [3.0, 2.0],
    [7.0, 3.0],
    [1.0, 1.0],
]
_Y_VALUES = [2 * row[0] + 3 * row[1] + 5 for row in _FEATURE_MATRIX]


def test_compute_mlr_recovers_exact_coefficients_from_noise_free_data() -> None:
    fit = compute_multiple_linear_regression(_FEATURE_MATRIX, _Y_VALUES, ["x1", "x2"])
    assert fit.intercept == pytest.approx(5.0)
    assert fit.coefficients == pytest.approx([2.0, 3.0])
    assert fit.r2 == pytest.approx(1.0)
    assert fit.adjusted_r2 == pytest.approx(1.0)
    assert fit.rmse == pytest.approx(0.0, abs=1e-9)
    assert fit.mae == pytest.approx(0.0, abs=1e-9)
    assert fit.n_observations == 10


def test_compute_mlr_with_noise_still_recovers_approximate_coefficients() -> None:
    rng_offsets = [0.05, -0.03, 0.02, -0.01, 0.04, -0.02, 0.01, -0.04, 0.03, -0.05]
    noisy_y = [_Y_VALUES[i] + rng_offsets[i] for i in range(len(_Y_VALUES))]
    fit = compute_multiple_linear_regression(_FEATURE_MATRIX, noisy_y, ["x1", "x2"])
    assert fit.intercept == pytest.approx(5.0, abs=0.2)
    assert fit.coefficients[0] == pytest.approx(2.0, abs=0.05)
    assert fit.coefficients[1] == pytest.approx(3.0, abs=0.05)
    assert fit.r2 > 0.99


def test_compute_mlr_requires_at_least_k_plus_2_observations() -> None:
    with pytest.raises(InsufficientObservationsError):
        compute_multiple_linear_regression([[1.0, 2.0], [2.0, 3.0]], [1.0, 2.0], ["x1", "x2"])


def test_compute_mlr_raises_on_collinear_predictors() -> None:
    # x2 is always exactly 2 * x1 — perfectly collinear, singular XtX.
    feature_matrix = [[1.0, 2.0], [2.0, 4.0], [3.0, 6.0], [4.0, 8.0], [5.0, 10.0]]
    y_values = [3.0, 5.0, 7.0, 9.0, 11.0]
    with pytest.raises(ValueError, match="collinear"):
        compute_multiple_linear_regression(feature_matrix, y_values, ["x1", "x2"])


def test_compute_mlr_is_agnostic_to_variable_count() -> None:
    """"Do not hardcode predictor variables" — three predictors work
    exactly the same way as two."""
    feature_matrix = [
        [1.0, 2.0, 1.0],
        [2.0, 1.0, 2.0],
        [3.0, 3.0, 1.0],
        [4.0, 2.0, 3.0],
        [5.0, 4.0, 2.0],
        [6.0, 1.0, 4.0],
    ]
    y_values = [2 * r[0] + 3 * r[1] + 1 * r[2] + 5 for r in feature_matrix]
    fit = compute_multiple_linear_regression(feature_matrix, y_values, ["x1", "x2", "x3"])
    assert fit.coefficients == pytest.approx([2.0, 3.0, 1.0])
    assert len(fit.coefficients) == 3
