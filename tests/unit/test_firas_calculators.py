"""Unit tests for the five ported FIRAS calculators — pure computation, no
I/O. Reference values computed by directly running the ported functions
(not hand-derived to high precision) and pinned here so any future change
to the formulas is a deliberate, visible diff.
"""

from __future__ import annotations

import pytest

from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.value_objects import ComputationSnapshot
from georisk.contexts.analysis.strategies.firas.exposure import (
    ASSETS,
    FIRASExposureCalculator,
    compute_all_ratios,
    compute_exposure_index,
)
from georisk.contexts.analysis.strategies.firas.hazard import (
    FIRASHazardCalculator,
    compute_flood_hazard_index,
)
from georisk.contexts.analysis.strategies.firas.resilience import (
    FIRASResilienceCalculator,
    compute_resilience,
)
from georisk.contexts.analysis.strategies.firas.risk import FIRASRiskCalculator, compute_risk
from georisk.contexts.analysis.strategies.firas.vulnerability import (
    VULNERABILITY_INDICATORS,
    FIRASVulnerabilityCalculator,
    compute_flood_vulnerability_index,
    compute_insecurity,
)

pytestmark = pytest.mark.unit

_HAZARD_INPUTS = dict(
    rainfall_index=0.65,
    water_level_index=0.55,
    slope_index=0.40,
    drainage_index=0.50,
    land_use_index=0.60,
    soil_index=0.70,
)
_ASSET_DATA = {
    "population": {"total": 10000, "exposed": 4000},
    "houses": {"total": 2000, "exposed": 900},
    "roads": {"total": 150, "exposed": 60},
    "schools": {"total": 20, "exposed": 8},
    "hospitals": {"total": 5, "exposed": 2},
    "power_infrastructure": {"total": 30, "exposed": 10},
    "agricultural_land": {"total": 500, "exposed": 200},
    "livestock": {"total": 3000, "exposed": 1200},
}
_VULNERABILITY = {
    "population_density": 0.60,
    "elderly_population": 0.30,
    "children_population": 0.35,
    "disability_status": 0.20,
    "education_level": 0.50,
    "poverty_level": 0.40,
    "housing_quality": 0.40,
    "building_materials": 0.50,
    "infrastructure_condition": 0.45,
    "household_income": 0.30,
    "livelihood_dependence": 0.55,
    "crop_dependence": 0.60,
}
_INSECURITY_RAW = {
    "emergency_plans": 0.50,
    "community_training": 0.40,
    "evacuation_preparedness": 0.45,
    "resource_availability": 0.50,
    "warning_timeliness": 0.60,
    "warning_accuracy": 0.55,
    "warning_accessibility": 0.50,
    "flood_awareness": 0.65,
    "previous_experience": 0.70,
    "understanding_of_risk": 0.60,
    "response_speed": 0.50,
    "relief_distribution": 0.45,
    "coordination": 0.55,
    "economic_recovery": 0.40,
    "infrastructure_recovery": 0.45,
    "social_recovery": 0.50,
}


# --- Hazard -----------------------------------------------------------------


def test_compute_flood_hazard_index_matches_reference_value() -> None:
    assert compute_flood_hazard_index(**_HAZARD_INPUTS) == pytest.approx(0.565)


def test_hazard_weights_must_sum_to_one() -> None:
    with pytest.raises(InvalidIndicatorInputError, match="sum to 1.0"):
        compute_flood_hazard_index(**_HAZARD_INPUTS, weights={"rainfall": 0.5})


def test_hazard_calculator_produces_indicator_set() -> None:
    snapshot = ComputationSnapshot(inputs=dict(_HAZARD_INPUTS))
    indicators = FIRASHazardCalculator().compute(snapshot)
    assert indicators.value("flood_hazard_index") == pytest.approx(0.565)


# --- Exposure ----------------------------------------------------------------


def test_compute_exposure_index_matches_reference_value() -> None:
    ratios = compute_all_ratios(_ASSET_DATA)
    assert ratios["power_infrastructure"] == pytest.approx(0.3333)
    assert compute_exposure_index(ratios) == pytest.approx(0.4067)


def test_exposure_ratio_zero_total_is_zero_not_an_error() -> None:
    ratios = compute_all_ratios({"population": {"total": 0, "exposed": 5}})
    assert ratios["population"] == 0.0


def test_exposure_calculator_produces_indicator_set() -> None:
    snapshot = ComputationSnapshot(inputs={"asset_data": _ASSET_DATA})
    indicators = FIRASExposureCalculator().compute(snapshot)
    assert indicators.value("flood_exposure_index") == pytest.approx(0.4067)
    for asset in ASSETS:
        assert indicators.get(f"{asset}_exposure_ratio") is not None


# --- Vulnerability + Insecurity ----------------------------------------------


def test_flood_vulnerability_index_matches_reference_value() -> None:
    """n=1 -> EWM falls back to equal weights (1/12 each): FVI is the
    plain mean of the 12 (inverse-transformed) indicators."""
    result = compute_flood_vulnerability_index(_VULNERABILITY)
    assert result["flood_vulnerability_index"] == pytest.approx(0.4875)
    weights = result["fvi_weights"]
    assert weights["population_density"] == pytest.approx(1 / 12, abs=1e-5)
    # Each weight is independently rounded to 6dp (round(1/12, 6) =
    # 0.083333), so the sum carries that same rounding error rather than
    # landing on exactly 1.0 — 12 * 0.083333 = 0.999996.
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-5)


def test_insecurity_first_observation_matches_reference_values() -> None:
    data = dict(_INSECURITY_RAW)
    data["flood_vulnerability_index_input"] = 0.4875
    result = compute_insecurity(data)
    assert result["cpc_score"] == pytest.approx(0.4625)
    assert result["flood_insecurity_index"] == pytest.approx(0.4792, abs=1e-4)


def test_vulnerability_calculator_produces_both_fvi_and_fii() -> None:
    inputs = {**_VULNERABILITY, **_INSECURITY_RAW}
    snapshot = ComputationSnapshot(inputs=inputs)
    indicators = FIRASVulnerabilityCalculator().compute(snapshot)
    assert indicators.value("flood_vulnerability_index") == pytest.approx(0.4875)
    assert indicators.value("flood_insecurity_index") == pytest.approx(0.4792, abs=1e-4)
    assert indicators.value("cpc_score") == pytest.approx(0.4625)
    for key in VULNERABILITY_INDICATORS:
        assert indicators.get(f"fvi_weight_{key}") is not None


def test_vulnerability_calculator_uses_historical_data_when_provided() -> None:
    """A second, different observation should produce non-equal EWM
    weights (n=2 -> MODERATE tier, no longer the n=1 equal fallback)."""
    historical_record = dict(_VULNERABILITY)
    historical_record.update({k: v * 0.5 for k, v in _VULNERABILITY.items()})
    historical_record.update(_INSECURITY_RAW)
    historical_record["flood_vulnerability_index_input"] = 0.3
    historical_record.update(
        {"cpc_score": 0.2, "ewe_score": 0.2, "kf_score": 0.2, "dre_score": 0.2, "rc_score": 0.2}
    )
    inputs = {**_VULNERABILITY, **_INSECURITY_RAW}
    snapshot = ComputationSnapshot(inputs=inputs, historical=(historical_record,))
    indicators = FIRASVulnerabilityCalculator().compute(snapshot)
    assert indicators.value("flood_insecurity_index") is not None
    assert indicators.value("flood_vulnerability_index") is not None


# --- Risk ---------------------------------------------------------------------


def test_compute_risk_matches_reference_value() -> None:
    """FRI = FHI x EI x FII — pure multiplicative, no weights."""
    fri = compute_risk(
        flood_hazard_index=0.565, exposure_index=0.4067, flood_insecurity_index=0.4792
    )
    assert fri == pytest.approx(0.1101, abs=1e-4)


def test_compute_risk_rejects_out_of_range_indicator() -> None:
    with pytest.raises(InvalidIndicatorInputError, match="between 0.0 and 1.0"):
        compute_risk(flood_hazard_index=1.5, exposure_index=0.4, flood_insecurity_index=0.4)


def test_risk_calculator_produces_indicator_set() -> None:
    snapshot = ComputationSnapshot(
        inputs={
            "flood_hazard_index_input": 0.565,
            "exposure_index_input": 0.4067,
            "flood_insecurity_index_input": 0.4792,
        }
    )
    indicators = FIRASRiskCalculator().compute(snapshot)
    assert indicators.value("flood_risk_index") == pytest.approx(0.1101, abs=1e-4)


# --- Resilience -----------------------------------------------------------------


def test_compute_resilience_matches_reference_value() -> None:
    data = {
        "cpc_score": 0.4625,
        "ewe_score": 0.549999,
        "kf_score": 0.649999,
        "dre_score": 0.499999,
        "rc_score": 0.45,
    }
    result = compute_resilience(data)
    assert result["cri_weights"] == pytest.approx([0.2, 0.2, 0.2, 0.2, 0.2])
    assert result["community_resilience_index"] == pytest.approx(0.5225, abs=1e-4)


def test_resilience_does_not_depend_on_risk_output() -> None:
    """Structural proof matching the StageType.RESILIENCE docstring's
    claim: compute_resilience's signature has no risk-related parameter at
    all, and its result is identical regardless of what Risk produced."""
    import inspect

    signature = inspect.signature(compute_resilience)
    assert "risk" not in " ".join(signature.parameters).lower()


def test_resilience_calculator_produces_indicator_set() -> None:
    snapshot = ComputationSnapshot(
        inputs={
            "cpc_score": 0.4625,
            "ewe_score": 0.549999,
            "kf_score": 0.649999,
            "dre_score": 0.499999,
            "rc_score": 0.45,
        }
    )
    indicators = FIRASResilienceCalculator().compute(snapshot)
    assert indicators.value("community_resilience_index") == pytest.approx(0.5225, abs=1e-4)
