"""WRRAS Module 8 — Wildfire Risk Index (WRI). Ported near-verbatim from
the legacy system's ``apps/wrras/risk.py``: pure multiplicative,
unweighted combination — ``WRI = WHI x WEI x WVI``. Already in this exact
form in the legacy code; no formula correction was needed here, unlike
FIRAS's Risk in Sprint 5.2.

Consumes Vulnerability **directly**, not Insecurity — the one structural
difference from FIRAS's Risk (``FRI = FHI x EI x FII``) that
``WRRAS_ARCHITECTURE_ALIGNMENT.md`` §1.1 names explicitly. Insecurity's
output feeds only Resilience (see ``resilience.py``), never Risk.
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    Indicator,
    IndicatorSet,
)

_KEYS: tuple[str, ...] = (
    "wildfire_hazard_index_input",
    "wildfire_exposure_index_input",
    "wildfire_vulnerability_index_input",
)


def compute_wildfire_risk_index(
    wildfire_hazard_index: float,
    wildfire_exposure_index: float,
    wildfire_vulnerability_index: float,
) -> float:
    """WRI = WHI x WEI x WVI — no weights, no EWM, no historical data."""
    for value, name in zip(
        (wildfire_hazard_index, wildfire_exposure_index, wildfire_vulnerability_index),
        ("wildfire_hazard_index", "wildfire_exposure_index", "wildfire_vulnerability_index"),
        strict=True,
    ):
        if not (0.0 <= value <= 1.0):
            raise InvalidIndicatorInputError(f"'{name}' must be between 0.0 and 1.0, got {value}")

    wri = wildfire_hazard_index * wildfire_exposure_index * wildfire_vulnerability_index
    return round(min(max(wri, 0.0), 1.0), 4)


class WRRASRiskCalculator:
    formula_version = "wri-multiplicative-v1"

    def compute(self, snapshot: ComputationSnapshot) -> IndicatorSet:
        inputs = snapshot.inputs
        wri = compute_wildfire_risk_index(*(inputs[k] for k in _KEYS))
        indicators = (Indicator(code="wildfire_risk_index", value=wri, unit="index"),)
        return IndicatorSet(indicators=indicators)
