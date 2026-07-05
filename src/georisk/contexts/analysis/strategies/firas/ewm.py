"""Entropy Weight Method (EWM) — ported from the legacy system's
``core/ewm.py`` (Platform Architecture §2: "Used by FIRAS's M4/M5/M6
weighting; deliberately not used by WRRAS ... proof that a shared module
is opt-in per strategy, never force-fit onto a hazard type that doesn't
call for it"). FIRAS-specific by design: this module lives inside
``strategies/firas/``, not as a shared cross-strategy utility, since no
other registered strategy uses it yet — a shared ``core.ewm`` extraction
is a decision for whenever a second consumer actually needs it, not before.

Reimplemented in pure Python rather than the legacy numpy-backed version —
the same policy that kept Sprint 4's ROC/AUC dependency-free: EWM's matrix
operations (column sums, log, normalize) are simple enough not to justify
adding numpy as a platform dependency for this alone.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from georisk.contexts.analysis.domain.value_objects import (
    ConfidenceTier,
    confidence_tier_for_sample_size,
)


def compute_weights(matrix: Sequence[Sequence[float]]) -> tuple[list[float], ConfidenceTier]:
    """Computes EWM weights from an (n_obs x n_indicators) matrix.

    Returns ``(weights, confidence)`` where ``weights`` sums to 1.0. Falls
    back to equal weights when ``n < 2`` (EWM undefined for a single
    observation) or when every indicator's degree of divergence is zero
    (all observations identical on every column).
    """
    n = len(matrix)
    m = len(matrix[0]) if n else 0
    tier = confidence_tier_for_sample_size(n)

    if n < 2 or m == 0:
        return [round(1.0 / m, 6) for _ in range(m)] if m else [], tier

    col_sums = [sum(row[j] for row in matrix) for j in range(m)]
    col_sums = [s if s != 0 else 1e-12 for s in col_sums]

    proportions = [[matrix[i][j] / col_sums[j] for j in range(m)] for i in range(n)]

    k = 1.0 / math.log(n)
    entropy = [0.0] * m
    for j in range(m):
        total = 0.0
        for i in range(n):
            p = proportions[i][j]
            total += p * math.log(p) if p > 0 else 0.0
        entropy[j] = -k * total

    divergence = [1.0 - e for e in entropy]
    divergence_total = sum(divergence)

    if divergence_total == 0:
        return [round(1.0 / m, 6) for _ in range(m)], tier

    weights = [round(d / divergence_total, 6) for d in divergence]
    return weights, tier
