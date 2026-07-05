"""WRRAS Module 5 — Wildfire Exposure Index (WEI). Ported near-verbatim
from the legacy system's ``apps/wrras/exposure.py``: equal-weight average
of four category exposure ratios (human, infrastructure, environmental,
economic).
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    Indicator,
    IndicatorSet,
)


def _ratio(exposed: float, total: float, name: str) -> float:
    if total < 0 or exposed < 0:
        raise InvalidIndicatorInputError(f"{name}: values must be >= 0")
    if total == 0:
        return 0.0
    if exposed > total:
        raise InvalidIndicatorInputError(
            f"{name}: exposed ({exposed}) cannot exceed total ({total})"
        )
    return round(exposed / total, 4)


def compute_wildfire_exposure_index(
    population_exposed: float,
    population_total: float,
    infrastructure_exposed: float,
    infrastructure_total: float,
    environmental_exposed: float,
    environmental_total: float,
    economic_exposed: float,
    economic_total: float,
) -> dict[str, float]:
    """WEI = (human_ratio + infrastructure_ratio + environmental_ratio + economic_ratio) / 4."""
    human_ratio = _ratio(population_exposed, population_total, "Human")
    infrastructure_ratio = _ratio(infrastructure_exposed, infrastructure_total, "Infrastructure")
    environmental_ratio = _ratio(environmental_exposed, environmental_total, "Environmental")
    economic_ratio = _ratio(economic_exposed, economic_total, "Economic")

    wei = round(
        (human_ratio + infrastructure_ratio + environmental_ratio + economic_ratio) / 4.0, 4
    )
    return {
        "wildfire_exposure_index": wei,
        "human_ratio": human_ratio,
        "infrastructure_ratio": infrastructure_ratio,
        "environmental_ratio": environmental_ratio,
        "economic_ratio": economic_ratio,
    }


class WRRASExposureCalculator:
    formula_version = "wei-equal-weight-average-v1"

    def compute(self, snapshot: ComputationSnapshot) -> IndicatorSet:
        inputs = snapshot.inputs
        result = compute_wildfire_exposure_index(
            population_exposed=inputs["population_exposed"],
            population_total=inputs["population_total"],
            infrastructure_exposed=inputs["infrastructure_exposed"],
            infrastructure_total=inputs["infrastructure_total"],
            environmental_exposed=inputs["environmental_exposed"],
            environmental_total=inputs["environmental_total"],
            economic_exposed=inputs["economic_exposed"],
            economic_total=inputs["economic_total"],
        )
        indicators = (
            Indicator(
                code="human_exposure_ratio",
                value=result["human_ratio"],
                unit="ratio",
                sub_index="categories",
            ),
            Indicator(
                code="infrastructure_exposure_ratio",
                value=result["infrastructure_ratio"],
                unit="ratio",
                sub_index="categories",
            ),
            Indicator(
                code="environmental_exposure_ratio",
                value=result["environmental_ratio"],
                unit="ratio",
                sub_index="categories",
            ),
            Indicator(
                code="economic_exposure_ratio",
                value=result["economic_ratio"],
                unit="ratio",
                sub_index="categories",
            ),
            Indicator(
                code="wildfire_exposure_index",
                value=result["wildfire_exposure_index"],
                unit="index",
            ),
        )
        return IndicatorSet(indicators=indicators)
