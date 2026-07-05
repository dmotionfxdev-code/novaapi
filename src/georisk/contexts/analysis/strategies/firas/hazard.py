"""FIRAS Module 1 — Flood Hazard Index (FHI). Ported near-verbatim from the
legacy system's ``apps/firas/hazard.py``: weighted linear combination of
six already-normalized 0-1 sub-indices, fixed default weights (no EWM —
only Insecurity/Risk/Resilience use entropy weighting in FIRAS).

``FIRASHazardCalculator.compute()`` is the ``StageCalculator`` adapter: it
extracts the six sub-index inputs from the ``ComputationSnapshot`` (in the
full platform these come from Geospatial/Data Acquisition; this sprint's
composition-root stub supplies fixed placeholder values — see
``application/ports.py``'s ``StubIndicatorInputProvider``) and calls the
pure formula below unchanged.
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    Indicator,
    IndicatorSet,
)

DEFAULT_WEIGHTS: dict[str, float] = {
    "rainfall": 0.25,
    "water_level": 0.25,
    "slope": 0.15,
    "drainage": 0.15,
    "land_use": 0.10,
    "soil": 0.10,
}

_INDEX_KEYS = (
    "rainfall_index",
    "water_level_index",
    "slope_index",
    "drainage_index",
    "land_use_index",
    "soil_index",
)
_WEIGHT_KEYS = ("rainfall", "water_level", "slope", "drainage", "land_use", "soil")


def _validate_index_range(value: float, name: str) -> None:
    if not (0.0 <= value <= 1.0):
        raise InvalidIndicatorInputError(f"'{name}' must be between 0.0 and 1.0, got {value}")


def _validate_weights(weights: dict[str, float]) -> None:
    total = sum(weights.values())
    if not (0.999 <= total <= 1.001):
        raise InvalidIndicatorInputError(f"Hazard weights must sum to 1.0, got {total:.4f}")


def compute_flood_hazard_index(
    rainfall_index: float,
    water_level_index: float,
    slope_index: float,
    drainage_index: float,
    land_use_index: float,
    soil_index: float,
    weights: dict[str, float] | None = None,
) -> float:
    """FHI = wR*R + wW*W + wS*S + wD*D + wL*L + wT*T."""
    weights = weights if weights is not None else DEFAULT_WEIGHTS
    _validate_weights(weights)
    for value, name in zip(
        (
            rainfall_index,
            water_level_index,
            slope_index,
            drainage_index,
            land_use_index,
            soil_index,
        ),
        _INDEX_KEYS,
        strict=True,
    ):
        _validate_index_range(value, name)

    fhi = (
        weights["rainfall"] * rainfall_index
        + weights["water_level"] * water_level_index
        + weights["slope"] * slope_index
        + weights["drainage"] * drainage_index
        + weights["land_use"] * land_use_index
        + weights["soil"] * soil_index
    )
    return round(min(max(fhi, 0.0), 1.0), 4)


class FIRASHazardCalculator:
    """Implements the ``StageCalculator`` protocol structurally (duck
    typing) — no base class, matching the rest of this codebase's
    Protocol usage (e.g. Sprint 3's ``ImmediateSuccessStageExecutor``)."""

    formula_version = "fhi-weighted-linear-v1"

    def compute(self, snapshot: ComputationSnapshot) -> IndicatorSet:
        inputs = snapshot.inputs
        weights = inputs.get("weights", DEFAULT_WEIGHTS)
        fhi = compute_flood_hazard_index(
            rainfall_index=inputs["rainfall_index"],
            water_level_index=inputs["water_level_index"],
            slope_index=inputs["slope_index"],
            drainage_index=inputs["drainage_index"],
            land_use_index=inputs["land_use_index"],
            soil_index=inputs["soil_index"],
            weights=weights,
        )
        indicators = [Indicator(code=key, value=inputs[key], unit="index") for key in _INDEX_KEYS]
        indicators.append(Indicator(code="flood_hazard_index", value=fhi, unit="index"))
        indicators.extend(
            Indicator(
                code=f"weight_{key}",
                value=weights.get(key, DEFAULT_WEIGHTS[key]),
                sub_index="weights",
            )
            for key in _WEIGHT_KEYS
        )
        return IndicatorSet(indicators=tuple(indicators))
