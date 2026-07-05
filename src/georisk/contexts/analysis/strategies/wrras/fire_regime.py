"""WRRAS Module 2 (partial) — Fire Regime Analysis. Optional, non-gating
supporting-analysis stage (``WRRAS_SCOPE_DECISION_LOG.md`` §1:
classification B — none of its outputs feed Hazard, Exposure,
Vulnerability, Risk, or Resilience, confirmed by grepping every core
formula module directly, not by inference). Never a
``required_predecessor`` of anything; must not affect Risk.

Ported near-verbatim from the legacy system's ``apps/wrras/fire_regime.py``.
Seven of its eight outputs are descriptive statistics over an accumulated
fire-incident history; the eighth (Fire Occurrence Probability, FOP) is a
fixed-coefficient logistic-regression forecast — conceptually a
Prediction-context artifact bundled in here for now (decision log §1.3),
not because it shares the others' descriptive nature.

**Known, unresolved issue** (decision log §2.1, carried forward, not
fixed here): FOP's formula is a near-duplicate of
``burn_probability.compute_burn_occurrence_probability`` — same sigmoid
structure, same six shared predictors, different literature-derived
coefficients. Kept as two separate calculators, exactly as the legacy
code has them, pending a formula-reconciliation decision.
"""

from __future__ import annotations

import math
from datetime import date

from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    Indicator,
    IndicatorSet,
)

_BETA: dict[str, float] = {
    "intercept": -4.0,
    "temperature": 3.0,
    "wind_speed": 2.0,
    "humidity_inv": 2.5,
    "fuel_load": 2.5,
    "drought_index": 2.0,
    "human_activity": 1.5,
}


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def compute_fire_regime(
    observation_years: float,
    fire_count: int,
    area_km2: float,
    repeated_burned_pixels: int,
    total_burned_pixels: int,
    burned_area_ha: float,
    first_fire_date: date,
    last_fire_date: date,
    high_severity_fires: int,
    temperature: float = 0.5,
    wind_speed: float = 0.5,
    relative_humidity: float = 0.5,
    fuel_load: float = 0.5,
    drought_index: float = 0.5,
    human_activity: float = 0.5,
) -> dict[str, float | None]:
    """Computes fire regime metrics from historical fire records."""
    if observation_years <= 0:
        raise InvalidIndicatorInputError("observation_years must be > 0")
    if area_km2 <= 0:
        raise InvalidIndicatorInputError("area_km2 must be > 0")
    if fire_count < 0:
        raise InvalidIndicatorInputError("fire_count must be >= 0")
    if total_burned_pixels < 0:
        raise InvalidIndicatorInputError("total_burned_pixels must be >= 0")

    ff = round(fire_count / observation_years, 4)
    fri = round(observation_years / fire_count, 4) if fire_count > 0 else None
    fod = round(fire_count / area_km2, 4)
    fpi = round(repeated_burned_pixels / total_burned_pixels, 4) if total_burned_pixels > 0 else 0.0
    bae = round(burned_area_ha, 4)
    fsl = (
        float((last_fire_date - first_fire_date).days) if last_fire_date >= first_fire_date else 0.0
    )
    fsf = round(high_severity_fires / fire_count, 4) if fire_count > 0 else 0.0

    humidity_inv = 1.0 - relative_humidity
    linear = (
        _BETA["intercept"]
        + _BETA["temperature"] * temperature
        + _BETA["wind_speed"] * wind_speed
        + _BETA["humidity_inv"] * humidity_inv
        + _BETA["fuel_load"] * fuel_load
        + _BETA["drought_index"] * drought_index
        + _BETA["human_activity"] * human_activity
    )
    fop = round(_sigmoid(linear), 4)

    return {
        "fire_frequency": ff,
        "fire_return_interval": fri,
        "fire_occurrence_density": fod,
        "fire_persistence_index": fpi,
        "burned_area_extent": bae,
        "fire_season_length": fsl,
        "fire_severity_frequency": fsf,
        "fire_occurrence_probability": fop,
    }


class WRRASFireRegimeCalculator:
    formula_version = "fire-regime-descriptive-plus-fop-v1"

    def compute(self, snapshot: ComputationSnapshot) -> IndicatorSet:
        inputs = snapshot.inputs
        result = compute_fire_regime(
            observation_years=inputs["observation_years"],
            fire_count=inputs["fire_count"],
            area_km2=inputs["area_km2"],
            repeated_burned_pixels=inputs["repeated_burned_pixels"],
            total_burned_pixels=inputs["total_burned_pixels"],
            burned_area_ha=inputs["burned_area_ha"],
            first_fire_date=date.fromisoformat(inputs["first_fire_date"]),
            last_fire_date=date.fromisoformat(inputs["last_fire_date"]),
            high_severity_fires=inputs["high_severity_fires"],
            temperature=inputs.get("temperature", 0.5),
            wind_speed=inputs.get("wind_speed", 0.5),
            relative_humidity=inputs.get("relative_humidity", 0.5),
            fuel_load=inputs.get("fuel_load", 0.5),
            drought_index=inputs.get("drought_index", 0.5),
            human_activity=inputs.get("human_activity", 0.5),
        )
        indicators = tuple(
            Indicator(code=key, value=float(value), unit="index")
            for key, value in result.items()
            if value is not None
        )
        return IndicatorSet(indicators=indicators)
