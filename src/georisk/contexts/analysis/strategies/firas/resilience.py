"""FIRAS Module 6 — Community Resilience Index (CRI). Ported near-verbatim
from the legacy system's ``apps/firas/resilience.py``: EWM-weighted
combination of the five sub-index scores Vulnerability's calculator already
produced (CPC, EWE, KF, DRE, RC) — no dependency on Risk's output at all,
which is exactly why this is a stage parallel to Risk, not nested inside
it (see the ``StageType.RESILIENCE`` addition's docstring,
``contexts/assessment/domain/workflow_value_objects.py``).
"""

from __future__ import annotations

from typing import TypedDict

from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    Indicator,
    IndicatorSet,
)
from georisk.contexts.analysis.strategies.firas.ewm import compute_weights

FORMULA_VERSION = "cri-ewm-v1"

_SUB_INDEX_KEYS: tuple[str, ...] = ("cpc_score", "ewe_score", "kf_score", "dre_score", "rc_score")


class ResilienceResult(TypedDict):
    cri_weights: list[float]
    community_resilience_index: float


def compute_resilience(
    insecurity_record: dict[str, float], historical: list[dict[str, float]] | None = None
) -> ResilienceResult:
    """CRI = w1*CPC + w2*EWE + w3*KF + w4*DRE + w5*RC, weights via EWM
    across all CRI observations."""
    hist = list(historical or [])
    matrix = [[rec[k] for k in _SUB_INDEX_KEYS] for rec in hist]
    matrix.append([insecurity_record[k] for k in _SUB_INDEX_KEYS])

    weights, _ = compute_weights(matrix)
    scores = [insecurity_record[k] for k in _SUB_INDEX_KEYS]
    cri = round(min(max(sum(w * s for w, s in zip(weights, scores, strict=True)), 0.0), 1.0), 4)

    return {"cri_weights": weights, "community_resilience_index": cri}


class FIRASResilienceCalculator:
    formula_version = FORMULA_VERSION

    def compute(self, snapshot: ComputationSnapshot) -> IndicatorSet:
        inputs = snapshot.inputs
        result = compute_resilience(
            {k: inputs[k] for k in _SUB_INDEX_KEYS}, historical=list(snapshot.historical)
        )
        cri_weights = result["cri_weights"]
        indicators = [
            Indicator(
                code=f"cri_weight_{key.removesuffix('_score')}", value=weight, sub_index="weights"
            )
            for key, weight in zip(_SUB_INDEX_KEYS, cri_weights, strict=True)
        ]
        indicators.append(
            Indicator(
                code="community_resilience_index",
                value=result["community_resilience_index"],
                unit="index",
            )
        )
        return IndicatorSet(indicators=tuple(indicators))
