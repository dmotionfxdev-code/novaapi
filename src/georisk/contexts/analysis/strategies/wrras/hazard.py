"""WRRAS Module 1 — Wildfire Hazard Index (WHI). Ported near-verbatim from
the legacy system's ``apps/wrras/hazard.py``: weighted linear combination
of eight already-normalized 0-1 sub-indices, fixed preset weights, no EWM
(``WRRAS_ARCHITECTURE_ALIGNMENT.md`` §2/§4 confirms no WRRAS formula uses
entropy weighting). Rainfall is inverted — higher rainfall means lower
hazard.
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    Indicator,
    IndicatorSet,
)

DEFAULT_WEIGHTS: dict[str, float] = {
    "temperature": 0.20,
    "wind_speed": 0.15,
    "drought_index": 0.15,
    "fuel_load": 0.15,
    "vegetation_density": 0.10,
    "slope": 0.10,
    "human_activity": 0.10,
    "rainfall": 0.05,  # inverted in the formula
}

_INDEX_KEYS = (
    "temperature",
    "wind_speed",
    "drought_index",
    "fuel_load",
    "vegetation_density",
    "slope",
    "human_activity",
    "rainfall",
)


def _validate_index_range(value: float, name: str) -> None:
    if not (0.0 <= value <= 1.0):
        raise InvalidIndicatorInputError(f"'{name}' must be between 0.0 and 1.0, got {value}")


def _validate_weights(weights: dict[str, float]) -> None:
    total = sum(weights.values())
    if not (0.999 <= total <= 1.001):
        raise InvalidIndicatorInputError(f"WRRAS hazard weights must sum to 1.0, got {total:.4f}")


def compute_wildfire_hazard_index(
    temperature: float,
    wind_speed: float,
    drought_index: float,
    fuel_load: float,
    vegetation_density: float,
    slope: float,
    human_activity: float,
    rainfall: float,
    weights: dict[str, float] | None = None,
) -> float:
    """WHI = 0.20T + 0.15W + 0.15D + 0.15F + 0.10V + 0.10S + 0.10H + 0.05(1-R)."""
    weights = weights if weights is not None else DEFAULT_WEIGHTS
    _validate_weights(weights)
    values = (
        temperature,
        wind_speed,
        drought_index,
        fuel_load,
        vegetation_density,
        slope,
        human_activity,
        rainfall,
    )
    for value, name in zip(values, _INDEX_KEYS, strict=True):
        _validate_index_range(value, name)

    rainfall_inv = 1.0 - rainfall
    whi = (
        weights["temperature"] * temperature
        + weights["wind_speed"] * wind_speed
        + weights["drought_index"] * drought_index
        + weights["fuel_load"] * fuel_load
        + weights["vegetation_density"] * vegetation_density
        + weights["slope"] * slope
        + weights["human_activity"] * human_activity
        + weights["rainfall"] * rainfall_inv
    )
    return round(min(max(whi, 0.0), 1.0), 4)


class WRRASHazardCalculator:
    formula_version = "whi-weighted-linear-v1"

    def compute(self, snapshot: ComputationSnapshot) -> IndicatorSet:
        inputs = snapshot.inputs
        weights = inputs.get("weights", DEFAULT_WEIGHTS)
        whi = compute_wildfire_hazard_index(
            **{key: inputs[key] for key in _INDEX_KEYS}, weights=weights
        )
        indicators = [Indicator(code=key, value=inputs[key], unit="index") for key in _INDEX_KEYS]
        indicators.append(Indicator(code="wildfire_hazard_index", value=whi, unit="index"))
        indicators.extend(
            Indicator(
                code=f"weight_{key}",
                value=weights.get(key, DEFAULT_WEIGHTS[key]),
                sub_index="weights",
            )
            for key in _INDEX_KEYS
        )
        return IndicatorSet(indicators=tuple(indicators))
