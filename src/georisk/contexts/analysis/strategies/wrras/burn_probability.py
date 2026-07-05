"""WRRAS Module 2 (partial) — Burn Occurrence Probability (BOP). Optional,
non-gating supporting-analysis stage — classified C) Prediction Context
Responsibility in ``WRRAS_SCOPE_DECISION_LOG.md`` §2 (built here as an
ordinary calculator since the platform has no Prediction context yet; may
migrate there later). Never a ``required_predecessor`` of anything; must
not affect Risk.

Ported near-verbatim from the legacy system's ``apps/wrras/burn_probability
.py``.

**Known, unresolved issue** (decision log §2.1, carried forward, not
fixed here): this is a near-duplicate of Fire Regime's own FOP
sub-calculation (``fire_regime.compute_fire_regime``) — same sigmoid
structure, same six shared predictors, different literature-derived
coefficients, plus one extra predictor (``historical_fire_index``) here.
Kept as two separate calculators, exactly as the legacy code has them,
pending a formula-reconciliation decision.
"""

from __future__ import annotations

import math

from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    Indicator,
    IndicatorSet,
)

_BETA: dict[str, float] = {
    "intercept": -3.5,
    "temperature": 2.5,
    "wind_speed": 2.0,
    "humidity_inv": 2.0,
    "fuel_load": 2.5,
    "drought_index": 2.0,
    "human_activity": 1.5,
    "historical_fires": 1.0,
}


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _validate(value: float, name: str) -> float:
    if not (0.0 <= value <= 1.0):
        raise InvalidIndicatorInputError(f"'{name}' must be between 0.0 and 1.0, got {value}")
    return float(value)


def compute_burn_occurrence_probability(
    temperature: float,
    wind_speed: float,
    relative_humidity: float,
    fuel_load: float,
    drought_index: float,
    human_activity: float,
    historical_fire_index: float,
) -> float:
    """P = sigmoid(β0 + Σβi·xi); relative_humidity is inverted (low
    humidity -> high fire risk)."""
    t = _validate(temperature, "temperature")
    w = _validate(wind_speed, "wind_speed")
    rh = _validate(relative_humidity, "relative_humidity")
    fl = _validate(fuel_load, "fuel_load")
    di = _validate(drought_index, "drought_index")
    ha = _validate(human_activity, "human_activity")
    hf = _validate(historical_fire_index, "historical_fire_index")

    humidity_inv = 1.0 - rh
    linear = (
        _BETA["intercept"]
        + _BETA["temperature"] * t
        + _BETA["wind_speed"] * w
        + _BETA["humidity_inv"] * humidity_inv
        + _BETA["fuel_load"] * fl
        + _BETA["drought_index"] * di
        + _BETA["human_activity"] * ha
        + _BETA["historical_fires"] * hf
    )
    return round(_sigmoid(linear), 4)


class WRRASBurnProbabilityCalculator:
    formula_version = "bop-logistic-v1"

    def compute(self, snapshot: ComputationSnapshot) -> IndicatorSet:
        inputs = snapshot.inputs
        bop = compute_burn_occurrence_probability(
            temperature=inputs["temperature"],
            wind_speed=inputs["wind_speed"],
            relative_humidity=inputs["relative_humidity"],
            fuel_load=inputs["fuel_load"],
            drought_index=inputs["drought_index"],
            human_activity=inputs["human_activity"],
            historical_fire_index=inputs["historical_fire_index"],
        )
        indicators = (Indicator(code="burn_occurrence_probability", value=bop, unit="probability"),)
        return IndicatorSet(indicators=indicators)
