"""FIRAS Module 2 — Flood Exposure Index (EI). Ported near-verbatim from
the legacy system's ``apps/firas/exposure.py``: weighted average of eight
asset-exposure ratios, fixed default weights.
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    Indicator,
    IndicatorSet,
)

ASSETS: tuple[str, ...] = (
    "population",
    "houses",
    "roads",
    "schools",
    "hospitals",
    "power_infrastructure",
    "agricultural_land",
    "livestock",
)

DEFAULT_WEIGHTS: dict[str, float] = {
    "population": 0.25,
    "houses": 0.20,
    "hospitals": 0.15,
    "schools": 0.10,
    "roads": 0.10,
    "agricultural_land": 0.10,
    "power_infrastructure": 0.05,
    "livestock": 0.05,
}


def _validate_weights(weights: dict[str, float]) -> None:
    total = sum(weights.values())
    if not (0.999 <= total <= 1.001):
        raise InvalidIndicatorInputError(f"Exposure weights must sum to 1.0, got {total:.4f}")


def compute_asset_exposure_ratio(exposed: float, total: float) -> float:
    """Ratio of exposed to total assets for one asset type. 0.0 when
    ``total`` is zero (no assets = no exposure); capped at 1.0."""
    if total <= 0:
        return 0.0
    return round(min(exposed / total, 1.0), 4)


def compute_all_ratios(asset_data: dict[str, dict[str, float]]) -> dict[str, float]:
    """``asset_data`` format: ``{'population': {'total': N, 'exposed': M}, ...}``."""
    return {
        asset: compute_asset_exposure_ratio(
            exposed=asset_data.get(asset, {}).get("exposed", 0),
            total=asset_data.get(asset, {}).get("total", 0),
        )
        for asset in ASSETS
    }


def compute_exposure_index(
    ratios: dict[str, float], weights: dict[str, float] | None = None
) -> float:
    """EI = Σ(wi * ri) where ri = exposed_i / total_i."""
    weights = weights if weights is not None else DEFAULT_WEIGHTS
    _validate_weights(weights)
    for asset, ratio in ratios.items():
        if not (0.0 <= ratio <= 1.0):
            raise InvalidIndicatorInputError(
                f"Ratio '{asset}' must be between 0.0 and 1.0, got {ratio}"
            )

    ei = sum(weights[asset] * ratios[asset] for asset in ASSETS)
    return round(min(max(ei, 0.0), 1.0), 4)


class FIRASExposureCalculator:
    formula_version = "ei-weighted-average-v1"

    def compute(self, snapshot: ComputationSnapshot) -> IndicatorSet:
        inputs = snapshot.inputs
        weights = inputs.get("weights", DEFAULT_WEIGHTS)
        ratios = compute_all_ratios(inputs["asset_data"])
        ei = compute_exposure_index(ratios, weights=weights)

        indicators = [
            Indicator(
                code=f"{asset}_exposure_ratio",
                value=ratios[asset],
                unit="ratio",
                sub_index="assets",
            )
            for asset in ASSETS
        ]
        indicators.append(Indicator(code="flood_exposure_index", value=ei, unit="index"))
        return IndicatorSet(indicators=tuple(indicators))
