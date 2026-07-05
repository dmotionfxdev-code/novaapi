"""FIRAS Module 5 — Flood Risk Index (FRI).

Sprint 5.2 (approved via ``GEORISK_SCOPE_REALIGNMENT.md`` §1.1 /
``GEORISK_SCOPE_AND_FORMULA_DECISION_LOG.md`` §1.1): FRI is a pure
multiplicative combination of Hazard, Exposure, and Insecurity —
``FRI = FHI x EI x FII`` — superseding the Sprint 5 EWM-weighted additive
form (``FRI = w1*FHI + w2*EI + w3*FII``). The FIRAS specification names
multiplicative combination explicitly; nothing here is weighted, and Risk
no longer has any historical-data or EWM dependency at all — a genuine
simplification, not just a formula swap.

``FIRASRiskCalculator.compute()`` still expects ``snapshot.inputs`` to
carry the three inputs read from Hazard/Exposure/Vulnerability's latest
``StageResult``s (``application/handlers.py``'s job — "reads ... results
via query, not live join," Application Layer §12).
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    Indicator,
    IndicatorSet,
)

FORMULA_VERSION = "fri-multiplicative-v2"

_KEYS: tuple[str, ...] = (
    "flood_hazard_index_input",
    "exposure_index_input",
    "flood_insecurity_index_input",
)


def compute_risk(
    flood_hazard_index: float, exposure_index: float, flood_insecurity_index: float
) -> float:
    """FRI = FHI x EI x FII — no weights, no EWM, no historical data."""
    for value, name in zip(
        (flood_hazard_index, exposure_index, flood_insecurity_index),
        ("flood_hazard_index", "exposure_index", "flood_insecurity_index"),
        strict=True,
    ):
        if not (0.0 <= value <= 1.0):
            raise InvalidIndicatorInputError(f"'{name}' must be between 0.0 and 1.0, got {value}")

    fri = flood_hazard_index * exposure_index * flood_insecurity_index
    return round(min(max(fri, 0.0), 1.0), 4)


class FIRASRiskCalculator:
    formula_version = FORMULA_VERSION

    def compute(self, snapshot: ComputationSnapshot) -> IndicatorSet:
        inputs = snapshot.inputs
        fri = compute_risk(*(inputs[k] for k in _KEYS))
        indicators = (Indicator(code="flood_risk_index", value=fri, unit="index"),)
        return IndicatorSet(indicators=indicators)
