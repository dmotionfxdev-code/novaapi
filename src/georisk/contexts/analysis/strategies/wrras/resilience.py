"""WRRAS Module 9 — Community Wildfire Resilience Index (CWRI). Ported
near-verbatim from the legacy system's ``apps/wrras/resilience.py``:
equal-weight average of the five sub-index scores Vulnerability's
calculator already produced (CPC, EWE, WKI, ERE, RC) — no dependency on
Risk's output at all, the same "parallel to Risk" structural reasoning
FIRAS's Resilience already established (``contexts/assessment/domain
/workflow_value_objects.py``'s ``StageType.RESILIENCE`` docstring).
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    Indicator,
    IndicatorSet,
)

_SUB_INDEX_KEYS: tuple[str, ...] = ("cpc_score", "ewe_score", "wki_score", "ere_score", "rc_score")


def compute_community_wildfire_resilience_index(data: dict[str, float]) -> float:
    """CWRI = (CPC + EWE + WKI + ERE + RC) / 5 — equal weights, no EWM."""
    scores = [data[key] for key in _SUB_INDEX_KEYS]
    for value, name in zip(scores, _SUB_INDEX_KEYS, strict=True):
        if not (0.0 <= value <= 1.0):
            raise InvalidIndicatorInputError(f"'{name}' must be between 0.0 and 1.0, got {value}")
    return round(sum(scores) / len(scores), 4)


class WRRASResilienceCalculator:
    formula_version = "cwri-equal-weight-v1"

    def compute(self, snapshot: ComputationSnapshot) -> IndicatorSet:
        inputs = snapshot.inputs
        cwri = compute_community_wildfire_resilience_index(
            {key: inputs[key] for key in _SUB_INDEX_KEYS}
        )
        indicators = (
            Indicator(code="community_wildfire_resilience_index", value=cwri, unit="index"),
        )
        return IndicatorSet(indicators=indicators)
