"""Unit tests for the Correlation Analysis Engine (Pearson/Spearman/
Kendall) — pure computation, no I/O. Reference values computed by
directly running the ported functions and pinned here so any future
change to the formulas is a deliberate, visible diff.
"""

from __future__ import annotations

import pytest

from georisk.contexts.prediction.domain.correlation import (
    compute_correlation_pairs,
    kendall_tau,
    pearson,
    spearman,
)
from georisk.contexts.prediction.domain.errors import InsufficientObservationsError

pytestmark = pytest.mark.unit


def test_pearson_perfect_positive_linear_relationship() -> None:
    x = (1.0, 2.0, 3.0, 4.0, 5.0)
    y = (2.0, 4.0, 6.0, 8.0, 10.0)
    assert pearson(x, y) == pytest.approx(1.0)


def test_pearson_noisy_relationship_matches_reference_value() -> None:
    x = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)
    y = (2.1, 3.9, 6.2, 7.8, 10.3, 11.9, 14.2, 15.8)
    assert pearson(x, y) == pytest.approx(0.999191, abs=1e-5)


def test_pearson_no_variance_returns_zero_not_an_error() -> None:
    x = (1.0, 1.0, 1.0)
    y = (2.0, 4.0, 6.0)
    assert pearson(x, y) == 0.0


def test_pearson_requires_at_least_two_observations() -> None:
    with pytest.raises(InsufficientObservationsError):
        pearson((1.0,), (2.0,))


def test_spearman_handles_ties_via_average_ranking() -> None:
    x = (1.0, 2.0, 2.0, 3.0, 4.0)
    y = (10.0, 20.0, 20.0, 30.0, 50.0)
    assert spearman(x, y) == pytest.approx(1.0)
    # Pearson on the same tied data is NOT 1.0 — proves rank transform matters.
    assert pearson(x, y) == pytest.approx(0.983135, abs=1e-5)


def test_spearman_monotonic_but_nonlinear_is_perfect() -> None:
    x = (1.0, 2.0, 3.0, 4.0, 5.0)
    y = (1.0, 4.0, 9.0, 16.0, 25.0)  # y = x^2, monotonic but not linear
    assert spearman(x, y) == pytest.approx(1.0)
    assert pearson(x, y) < 1.0


def test_kendall_tau_perfect_concordance() -> None:
    x = (1.0, 2.0, 3.0, 4.0, 5.0)
    y = (10.0, 20.0, 30.0, 40.0, 50.0)
    assert kendall_tau(x, y) == pytest.approx(1.0)


def test_kendall_tau_perfect_discordance() -> None:
    x = (1.0, 2.0, 3.0, 4.0, 5.0)
    y = (50.0, 40.0, 30.0, 20.0, 10.0)
    assert kendall_tau(x, y) == pytest.approx(-1.0)


def test_kendall_tau_matches_reference_value() -> None:
    x = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0)
    y = (2.1, 3.9, 6.2, 7.8, 10.3, 11.9, 14.2, 15.8)
    assert kendall_tau(x, y) == pytest.approx(1.0)


def test_kendall_tau_subsamples_beyond_the_documented_cap() -> None:
    from georisk.contexts.prediction.domain.correlation import MAX_KENDALL_OBSERVATIONS

    n = MAX_KENDALL_OBSERVATIONS + 200
    x = tuple(float(i) for i in range(n))
    y = tuple(float(i) * 2.0 for i in range(n))
    # Should still complete quickly and report perfect concordance —
    # proves the subsample doesn't corrupt an otherwise-perfect signal.
    assert kendall_tau(x, y) == pytest.approx(1.0)


def test_compute_correlation_pairs_covers_every_unordered_pair() -> None:
    """"Do not hardcode predictor variables": however many variable
    codes are present, that's how many pairs come out."""
    data = {
        "ndvi": (0.1, 0.2, 0.3, 0.4),
        "wind_speed": (0.4, 0.3, 0.2, 0.1),
        "rainfall": (0.5, 0.5, 0.5, 0.5),
    }
    pairs = compute_correlation_pairs(data, "PEARSON_CORRELATION")
    pair_keys = {frozenset((a, b)) for a, b, _coeff, _n in pairs}
    assert pair_keys == {
        frozenset({"ndvi", "wind_speed"}),
        frozenset({"ndvi", "rainfall"}),
        frozenset({"wind_speed", "rainfall"}),
    }
    assert len(pairs) == 3
