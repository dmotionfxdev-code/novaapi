"""Unit tests for the eight ported WRRAS calculators — pure computation,
no I/O. Reference values computed by directly running the ported
functions (not hand-derived to high precision) and pinned here so any
future change to the formulas is a deliberate, visible diff.
"""

from __future__ import annotations

import pytest

from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.value_objects import ComputationSnapshot
from georisk.contexts.analysis.strategies.wrras.burn_probability import (
    WRRASBurnProbabilityCalculator,
    compute_burn_occurrence_probability,
)
from georisk.contexts.analysis.strategies.wrras.burn_severity import (
    WRRASBurnSeverityCalculator,
    compute_burn_severity,
)
from georisk.contexts.analysis.strategies.wrras.exposure import (
    WRRASExposureCalculator,
    compute_wildfire_exposure_index,
)
from georisk.contexts.analysis.strategies.wrras.fire_regime import (
    WRRASFireRegimeCalculator,
    compute_fire_regime,
)
from georisk.contexts.analysis.strategies.wrras.hazard import (
    WRRASHazardCalculator,
    compute_wildfire_hazard_index,
)
from georisk.contexts.analysis.strategies.wrras.resilience import (
    WRRASResilienceCalculator,
    compute_community_wildfire_resilience_index,
)
from georisk.contexts.analysis.strategies.wrras.risk import (
    WRRASRiskCalculator,
    compute_wildfire_risk_index,
)
from georisk.contexts.analysis.strategies.wrras.vulnerability import (
    WRRASVulnerabilityCalculator,
    compute_wildfire_insecurity_index,
    compute_wildfire_vulnerability_index,
)

pytestmark = pytest.mark.unit

_HAZARD_INPUTS = dict(
    temperature=0.70,
    wind_speed=0.55,
    drought_index=0.60,
    fuel_load=0.65,
    vegetation_density=0.60,
    slope=0.40,
    human_activity=0.35,
    rainfall=0.30,
)
_EXPOSURE_INPUTS = dict(
    population_exposed=3500,
    population_total=10000,
    infrastructure_exposed=800,
    infrastructure_total=2000,
    environmental_exposed=150,
    environmental_total=500,
    economic_exposed=400,
    economic_total=1000,
)
_VULNERABILITY = {
    "poverty_rate": 0.45,
    "literacy_level": 0.65,
    "age_dependency_ratio": 0.40,
    "disability_ratio": 0.15,
    "building_flammability": 0.55,
    "roof_material_index": 0.50,
    "building_density": 0.45,
    "access_road_quality": 0.60,
    "fuel_accumulation_index": 0.60,
    "ecosystem_sensitivity": 0.50,
    "forest_condition": 0.55,
    "tourism_dependence": 0.35,
    "forest_livelihood_dependence": 0.50,
    "agricultural_dependence": 0.45,
}
_INSECURITY = {
    "firebreak_coverage": 0.45,
    "community_training": 0.40,
    "fire_committee_presence": 0.35,
    "equipment_availability": 0.40,
    "warning_timeliness": 0.55,
    "warning_accessibility": 0.50,
    "warning_accuracy": 0.55,
    "fire_awareness": 0.60,
    "fire_prevention_knowledge": 0.50,
    "evacuation_knowledge": 0.45,
    "response_time_index": 0.50,
    "suppression_efficiency": 0.45,
    "resource_adequacy": 0.40,
    "forest_restoration": 0.40,
    "economic_recovery": 0.35,
    "community_recovery": 0.45,
}


# --- Hazard -------------------------------------------------------------


def test_compute_wildfire_hazard_index_matches_reference_value() -> None:
    assert compute_wildfire_hazard_index(**_HAZARD_INPUTS) == pytest.approx(0.58)


def test_hazard_weights_must_sum_to_one() -> None:
    with pytest.raises(InvalidIndicatorInputError, match="sum to 1.0"):
        compute_wildfire_hazard_index(**_HAZARD_INPUTS, weights={"temperature": 0.5})


def test_hazard_calculator_produces_indicator_set() -> None:
    snapshot = ComputationSnapshot(inputs=dict(_HAZARD_INPUTS))
    indicators = WRRASHazardCalculator().compute(snapshot)
    assert indicators.value("wildfire_hazard_index") == pytest.approx(0.58)


# --- Exposure -------------------------------------------------------------


def test_compute_wildfire_exposure_index_matches_reference_value() -> None:
    result = compute_wildfire_exposure_index(**_EXPOSURE_INPUTS)
    assert result["wildfire_exposure_index"] == pytest.approx(0.3625)
    assert result["human_ratio"] == pytest.approx(0.35)


def test_exposure_calculator_produces_indicator_set() -> None:
    snapshot = ComputationSnapshot(inputs=dict(_EXPOSURE_INPUTS))
    indicators = WRRASExposureCalculator().compute(snapshot)
    assert indicators.value("wildfire_exposure_index") == pytest.approx(0.3625)


# --- Vulnerability + Insecurity --------------------------------------------


def test_wildfire_vulnerability_index_matches_reference_value() -> None:
    result = compute_wildfire_vulnerability_index(_VULNERABILITY)
    assert result["wildfire_vulnerability_index"] == pytest.approx(0.4406)
    assert result["social_vulnerability"] == pytest.approx(0.3375)
    assert result["physical_vulnerability"] == pytest.approx(0.475)


def test_wildfire_insecurity_index_matches_reference_value() -> None:
    result = compute_wildfire_insecurity_index(_INSECURITY, wildfire_vulnerability_index=0.4406)
    assert result["cpc_score"] == pytest.approx(0.40)
    assert result["wildfire_insecurity_index"] == pytest.approx(0.5234, abs=1e-4)


def test_vulnerability_calculator_produces_both_wvi_and_wii() -> None:
    inputs = {**_VULNERABILITY, **_INSECURITY}
    snapshot = ComputationSnapshot(inputs=inputs)
    indicators = WRRASVulnerabilityCalculator().compute(snapshot)
    assert indicators.value("wildfire_vulnerability_index") == pytest.approx(0.4406)
    assert indicators.value("wildfire_insecurity_index") == pytest.approx(0.5234, abs=1e-4)
    assert indicators.value("cpc_score") == pytest.approx(0.40)


# --- Risk -------------------------------------------------------------------


def test_compute_wildfire_risk_index_matches_reference_value() -> None:
    wri = compute_wildfire_risk_index(
        wildfire_hazard_index=0.58,
        wildfire_exposure_index=0.3625,
        wildfire_vulnerability_index=0.4406,
    )
    assert wri == pytest.approx(0.0926, abs=1e-4)


def test_compute_risk_rejects_out_of_range_indicator() -> None:
    with pytest.raises(InvalidIndicatorInputError, match="between 0.0 and 1.0"):
        compute_wildfire_risk_index(
            wildfire_hazard_index=1.5, wildfire_exposure_index=0.4, wildfire_vulnerability_index=0.4
        )


def test_risk_calculator_produces_indicator_set() -> None:
    snapshot = ComputationSnapshot(
        inputs={
            "wildfire_hazard_index_input": 0.58,
            "wildfire_exposure_index_input": 0.3625,
            "wildfire_vulnerability_index_input": 0.4406,
        }
    )
    indicators = WRRASRiskCalculator().compute(snapshot)
    assert indicators.value("wildfire_risk_index") == pytest.approx(0.0926, abs=1e-4)


# --- Resilience ---------------------------------------------------------------


def test_compute_community_wildfire_resilience_index_matches_reference_value() -> None:
    cwri = compute_community_wildfire_resilience_index(
        {
            "cpc_score": 0.40,
            "ewe_score": 0.5333,
            "wki_score": 0.5167,
            "ere_score": 0.45,
            "rc_score": 0.40,
        }
    )
    assert cwri == pytest.approx(0.46, abs=1e-4)


def test_resilience_calculator_produces_indicator_set() -> None:
    snapshot = ComputationSnapshot(
        inputs={
            "cpc_score": 0.40,
            "ewe_score": 0.5333,
            "wki_score": 0.5167,
            "ere_score": 0.45,
            "rc_score": 0.40,
        }
    )
    indicators = WRRASResilienceCalculator().compute(snapshot)
    assert indicators.value("community_wildfire_resilience_index") == pytest.approx(0.46, abs=1e-4)


def test_resilience_does_not_depend_on_risk_output() -> None:
    import inspect

    signature = inspect.signature(compute_community_wildfire_resilience_index)
    assert "risk" not in " ".join(signature.parameters).lower()


# --- Optional supporting-analysis stages --------------------------------------


def test_compute_fire_regime_matches_reference_values() -> None:
    from datetime import date

    result = compute_fire_regime(
        observation_years=10.0,
        fire_count=15,
        area_km2=250.0,
        repeated_burned_pixels=800,
        total_burned_pixels=2000,
        burned_area_ha=1500.0,
        first_fire_date=date(2015, 6, 1),
        last_fire_date=date(2025, 9, 15),
        high_severity_fires=4,
        temperature=0.70,
        wind_speed=0.55,
        relative_humidity=0.40,
        fuel_load=0.65,
        drought_index=0.60,
        human_activity=0.35,
    )
    assert result["fire_frequency"] == pytest.approx(1.5)
    assert result["fire_occurrence_probability"] == pytest.approx(0.9829, abs=1e-4)
    assert result["fire_season_length"] == 3759


def test_fire_regime_calculator_produces_indicator_set() -> None:
    snapshot = ComputationSnapshot(
        inputs={
            "observation_years": 10.0,
            "fire_count": 15,
            "area_km2": 250.0,
            "repeated_burned_pixels": 800,
            "total_burned_pixels": 2000,
            "burned_area_ha": 1500.0,
            "first_fire_date": "2015-06-01",
            "last_fire_date": "2025-09-15",
            "high_severity_fires": 4,
            "temperature": 0.70,
            "wind_speed": 0.55,
            "relative_humidity": 0.40,
            "fuel_load": 0.65,
            "drought_index": 0.60,
            "human_activity": 0.35,
        }
    )
    indicators = WRRASFireRegimeCalculator().compute(snapshot)
    assert indicators.value("fire_frequency") == pytest.approx(1.5)
    assert indicators.value("fire_occurrence_probability") == pytest.approx(0.9829, abs=1e-4)


def test_fire_regime_with_zero_fires_omits_undefined_return_interval() -> None:
    from datetime import date

    result = compute_fire_regime(
        observation_years=10.0,
        fire_count=0,
        area_km2=250.0,
        repeated_burned_pixels=0,
        total_burned_pixels=0,
        burned_area_ha=0.0,
        first_fire_date=date(2015, 1, 1),
        last_fire_date=date(2015, 1, 1),
        high_severity_fires=0,
    )
    assert result["fire_return_interval"] is None


def test_compute_burn_occurrence_probability_matches_reference_value() -> None:
    bop = compute_burn_occurrence_probability(
        temperature=0.70,
        wind_speed=0.55,
        relative_humidity=0.40,
        fuel_load=0.65,
        drought_index=0.60,
        human_activity=0.35,
        historical_fire_index=0.50,
    )
    assert bop == pytest.approx(0.9879, abs=1e-4)


def test_burn_probability_calculator_produces_indicator_set() -> None:
    snapshot = ComputationSnapshot(
        inputs={
            "temperature": 0.70,
            "wind_speed": 0.55,
            "relative_humidity": 0.40,
            "fuel_load": 0.65,
            "drought_index": 0.60,
            "human_activity": 0.35,
            "historical_fire_index": 0.50,
        }
    )
    indicators = WRRASBurnProbabilityCalculator().compute(snapshot)
    assert indicators.value("burn_occurrence_probability") == pytest.approx(0.9879, abs=1e-4)


def test_burn_probability_and_fire_regime_fop_are_a_known_duplication() -> None:
    """Structural proof matching WRRAS_SCOPE_DECISION_LOG.md §2.1: both
    modules independently estimate fire-occurrence likelihood via a
    sigmoid over almost the same predictors — a known, unresolved
    redundancy, not a bug in either individual formula."""
    import inspect

    bop_params = set(inspect.signature(compute_burn_occurrence_probability).parameters)
    fire_regime_params = set(inspect.signature(compute_fire_regime).parameters)
    shared = {"temperature", "wind_speed", "fuel_load", "drought_index", "human_activity"}
    assert shared.issubset(bop_params)
    assert shared.issubset(fire_regime_params)


def test_compute_burn_severity_matches_reference_values() -> None:
    result = compute_burn_severity(
        nir_pre=0.45, swir_pre=0.20, nir_post=0.25, swir_post=0.30, red_pre=0.08, red_post=0.18
    )
    assert result["nbr_pre"] == pytest.approx(0.3846, abs=1e-4)
    assert result["dnbr"] == pytest.approx(0.4755, abs=1e-4)
    assert result["dbai"] == pytest.approx(16.972, abs=1e-3)


def test_burn_severity_rejects_out_of_range_band() -> None:
    with pytest.raises(InvalidIndicatorInputError, match=r"\[0, 1\]"):
        compute_burn_severity(
            nir_pre=1.5, swir_pre=0.20, nir_post=0.25, swir_post=0.30, red_pre=0.08, red_post=0.18
        )


def test_burn_severity_calculator_produces_indicator_set() -> None:
    snapshot = ComputationSnapshot(
        inputs={
            "nir_pre": 0.45,
            "swir_pre": 0.20,
            "nir_post": 0.25,
            "swir_post": 0.30,
            "red_pre": 0.08,
            "red_post": 0.18,
        }
    )
    indicators = WRRASBurnSeverityCalculator().compute(snapshot)
    assert indicators.value("dnbr") == pytest.approx(0.4755, abs=1e-4)
