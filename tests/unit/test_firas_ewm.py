"""Unit tests for the ported Entropy Weight Method (`strategies.firas.ewm`)
— pure computation, no I/O.
"""

from __future__ import annotations

import pytest

from georisk.contexts.analysis.domain.value_objects import ConfidenceTier
from georisk.contexts.analysis.strategies.firas.ewm import compute_weights

pytestmark = pytest.mark.unit


def test_single_observation_falls_back_to_equal_weights_low_confidence() -> None:
    weights, tier = compute_weights([[0.5, 0.3, 0.2]])
    assert weights == pytest.approx([1 / 3, 1 / 3, 1 / 3])
    assert tier is ConfidenceTier.LOW


def test_weights_always_sum_to_one() -> None:
    matrix = [[0.5, 0.3, 0.2], [0.6, 0.1, 0.3], [0.4, 0.4, 0.2], [0.55, 0.25, 0.2], [0.3, 0.5, 0.2]]
    weights, tier = compute_weights(matrix)
    assert sum(weights) == pytest.approx(1.0, abs=1e-6)
    assert tier is ConfidenceTier.HIGH


def test_confidence_tier_thresholds() -> None:
    _, tier_1 = compute_weights([[0.5, 0.5]])
    _, tier_2 = compute_weights([[0.5, 0.5], [0.4, 0.6]])
    _, tier_4 = compute_weights([[0.5, 0.5]] * 4)
    _, tier_5 = compute_weights([[0.5, 0.5]] * 5)
    assert tier_1 is ConfidenceTier.LOW
    assert tier_2 is ConfidenceTier.MODERATE
    assert tier_4 is ConfidenceTier.MODERATE
    assert tier_5 is ConfidenceTier.HIGH


def test_identical_observations_fall_back_to_equal_weights() -> None:
    """All rows identical -> zero entropy divergence on every column ->
    the degree-of-divergence-sums-to-zero fallback path."""
    matrix = [[0.5, 0.5, 0.5]] * 3
    weights, _ = compute_weights(matrix)
    assert weights == pytest.approx([1 / 3, 1 / 3, 1 / 3])


def test_more_variable_column_gets_higher_weight() -> None:
    """EWM's core property: a column with more variation across
    observations (more "information") should receive a higher weight than
    a column that barely varies."""
    matrix = [
        [0.1, 0.50],
        [0.9, 0.51],
        [0.2, 0.49],
        [0.8, 0.50],
    ]
    weights, _ = compute_weights(matrix)
    assert weights[0] > weights[1]
