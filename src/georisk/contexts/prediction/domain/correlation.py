"""Correlation Analysis Engine (Sprint 8 requirement #2) — Pearson,
Spearman, and Kendall's tau-b, pure Python, no numpy/scipy dependency
(this codebase's established policy — ``strategies/firas/ewm.py``'s
docstring sets the precedent — of not adding a heavy dependency for
math this size). No existing implementation to port: the legacy system's
FIRAS specification describes "Perform Correlation Analysis" (Pearson/
Spearman/Kendall, multicollinearity/VIF) narratively, in prose, but never
implemented it in code (confirmed by search — no ``pearson``/``spearman``/
``kendall`` anywhere in ``old-system/``) — this is a fresh implementation
against the standard textbook formulas, not a port.
"""

from __future__ import annotations

import math

from georisk.contexts.prediction.domain.errors import InsufficientObservationsError

# Kendall's tau-b is the one O(n^2) algorithm here (pairwise concordant/
# discordant counting) — deliberately not the O(n log n) merge-sort
# variant: that requires careful tie-correction bookkeeping that's easy
# to get subtly wrong and hard to verify without a scipy reference to
# check against, whereas the pairwise version is simple enough to hand-
# verify for the unit tests. To keep worst-case latency bounded for a
# large SamplingCampaign (up to 5,000 points,
# GEORISK_SCOPE_REALIGNMENT.md §4), Kendall's tau is computed against a
# deterministic, documented subsample rather than every point — a
# pragmatic, honest tradeoff, not a silent limitation.
MAX_KENDALL_OBSERVATIONS = 500


def _validate_equal_length(x: tuple[float, ...], y: tuple[float, ...]) -> None:
    if len(x) != len(y):
        raise ValueError(f"x and y must have the same length, got {len(x)} and {len(y)}")
    if len(x) < 2:
        raise InsufficientObservationsError("Correlation requires at least 2 observations")


def pearson(x: tuple[float, ...], y: tuple[float, ...]) -> float:
    """r = cov(x, y) / (std(x) * std(y))."""
    _validate_equal_length(x, y)
    n = len(x)
    x_mean = sum(x) / n
    y_mean = sum(y) / n
    cov = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    x_var = sum((v - x_mean) ** 2 for v in x)
    y_var = sum((v - y_mean) ** 2 for v in y)
    denom = math.sqrt(x_var * y_var)
    if denom == 0:
        return 0.0
    return round(max(-1.0, min(1.0, cov / denom)), 6)


def _average_ranks(values: tuple[float, ...]) -> list[float]:
    """Ranks ``values`` ascending, giving tied values the average of the
    ranks they'd otherwise span (the standard Spearman tie-handling
    rule)."""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        average_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = average_rank
        i = j + 1
    return ranks


def spearman(x: tuple[float, ...], y: tuple[float, ...]) -> float:
    """Pearson correlation computed over the rank transform of x and y."""
    _validate_equal_length(x, y)
    x_ranks = tuple(_average_ranks(x))
    y_ranks = tuple(_average_ranks(y))
    return pearson(x_ranks, y_ranks)


def _subsample_deterministic(
    x: tuple[float, ...], y: tuple[float, ...], max_observations: int
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    n = len(x)
    if n <= max_observations:
        return x, y
    stride = n / max_observations
    indices = [int(i * stride) for i in range(max_observations)]
    return tuple(x[i] for i in indices), tuple(y[i] for i in indices)


def kendall_tau(x: tuple[float, ...], y: tuple[float, ...]) -> float:
    """Kendall's tau-b (tie-corrected). See module docstring for the
    deterministic subsampling applied above ``MAX_KENDALL_OBSERVATIONS``.
    """
    _validate_equal_length(x, y)
    x, y = _subsample_deterministic(x, y, MAX_KENDALL_OBSERVATIONS)
    n = len(x)

    concordant = 0
    discordant = 0
    x_ties = 0
    y_ties = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = x[i] - x[j]
            dy = y[i] - y[j]
            if dx == 0 and dy == 0:
                x_ties += 1
                y_ties += 1
            elif dx == 0:
                x_ties += 1
            elif dy == 0:
                y_ties += 1
            elif (dx > 0) == (dy > 0):
                concordant += 1
            else:
                discordant += 1

    n0 = n * (n - 1) / 2
    denom = math.sqrt((n0 - x_ties) * (n0 - y_ties))
    if denom == 0:
        return 0.0
    return round(max(-1.0, min(1.0, (concordant - discordant) / denom)), 6)


_METHOD_FUNCTIONS = {
    "PEARSON_CORRELATION": pearson,
    "SPEARMAN_CORRELATION": spearman,
    "KENDALL_CORRELATION": kendall_tau,
}


def compute_correlation_pairs(
    data: dict[str, tuple[float, ...]], method: str
) -> list[tuple[str, str, float, int]]:
    """Every pairwise coefficient among ``data``'s variable codes — "Do
    not hardcode predictor variables": however many codes ``data``
    contains, that's how many pairs come out, never a fixed shape.
    Returns a list of ``(variable_a, variable_b, coefficient,
    sample_size)`` tuples, one per unordered pair.
    """
    compute = _METHOD_FUNCTIONS[method]
    codes = sorted(data.keys())
    pairs = []
    for i, code_a in enumerate(codes):
        for code_b in codes[i + 1 :]:
            coefficient = compute(data[code_a], data[code_b])
            pairs.append((code_a, code_b, coefficient, len(data[code_a])))
    return pairs
