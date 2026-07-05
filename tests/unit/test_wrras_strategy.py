"""Unit tests for ``WRRASHazardStrategy`` — pure logic, no I/O. Proves the
registry's "callers never change to accommodate a new registrant"
property a second time, independently of FIRAS, and proves the three
optional supporting-analysis stages are genuinely non-gating.
"""

from __future__ import annotations

import pytest

from georisk.contexts.analysis.application.strategy_registry import StrategyRegistry
from georisk.contexts.analysis.domain.errors import NoCalculatorRegisteredError
from georisk.contexts.analysis.domain.value_objects import HazardType, StageType
from georisk.contexts.analysis.strategies.wrras.risk import WRRASRiskCalculator
from georisk.contexts.analysis.strategies.wrras.strategy import WRRASHazardStrategy

pytestmark = pytest.mark.unit


def test_supported_stages_covers_five_core_plus_three_optional_calculators() -> None:
    strategy = WRRASHazardStrategy()
    assert strategy.supported_stages() == {
        StageType.HAZARD,
        StageType.EXPOSURE,
        StageType.VULNERABILITY,
        StageType.RISK,
        StageType.RESILIENCE,
        StageType.FIRE_REGIME,
        StageType.BURN_OCCURRENCE_PROBABILITY,
        StageType.BURN_SEVERITY,
    }


def test_supported_stages_excludes_validation() -> None:
    strategy = WRRASHazardStrategy()
    assert StageType.VALIDATION not in strategy.supported_stages()


def test_get_calculator_returns_the_right_type() -> None:
    strategy = WRRASHazardStrategy()
    assert isinstance(strategy.get_calculator(StageType.RISK), WRRASRiskCalculator)


def test_get_calculator_raises_for_unsupported_stage() -> None:
    strategy = WRRASHazardStrategy()
    with pytest.raises(NoCalculatorRegisteredError):
        strategy.get_calculator(StageType.VALIDATION)


def test_strategy_and_calculators_report_version_metadata() -> None:
    strategy = WRRASHazardStrategy()
    assert strategy.strategy_version == "wrras-1.0"
    for stage_type in strategy.supported_stages():
        calculator = strategy.get_calculator(stage_type)
        assert isinstance(calculator.formula_version, str)
        assert calculator.formula_version


def test_uses_no_historical_data_anywhere() -> None:
    """WRRAS_ARCHITECTURE_ALIGNMENT.md §2/§4: no EWM anywhere in WRRAS —
    unlike FIRAS's Vulnerability/Resilience, nothing here needs
    historical comparison data."""
    strategy = WRRASHazardStrategy()
    assert strategy.historical_stages() == frozenset()


def test_risk_depends_on_vulnerability_directly_not_insecurity() -> None:
    """The one structural difference from FIRAS's Risk
    (WRRAS_ARCHITECTURE_ALIGNMENT.md §1.1): WRI consumes WVI directly."""
    strategy = WRRASHazardStrategy()
    dependencies = strategy.input_dependencies(StageType.RISK)
    assert StageType.VULNERABILITY in dependencies
    assert "wildfire_vulnerability_index" in dependencies[StageType.VULNERABILITY]


def test_optional_supporting_analysis_stages_have_no_input_dependencies() -> None:
    """Fire Regime, Burn Occurrence Probability, and Burn Severity read
    raw external data (via IndicatorInputProvider), never a prior
    StageResult — WRRAS_SCOPE_DECISION_LOG.md confirmed none of them
    consumes, or is consumed by, any of the five core formulas."""
    strategy = WRRASHazardStrategy()
    for stage_type in (
        StageType.FIRE_REGIME,
        StageType.BURN_OCCURRENCE_PROBABILITY,
        StageType.BURN_SEVERITY,
    ):
        assert strategy.input_dependencies(stage_type) == {}


def test_registry_resolves_registered_wildfire_strategy_independently_of_flood() -> None:
    """The core extensibility claim, proven a second time: registering
    WRRAS does not disturb FIRAS, and vice versa."""
    from georisk.contexts.analysis.strategies.firas.strategy import FIRASHazardStrategy

    registry = StrategyRegistry()
    registry.register(HazardType.FLOOD, FIRASHazardStrategy())
    registry.register(HazardType.WILDFIRE, WRRASHazardStrategy())

    assert registry.resolve(HazardType.FLOOD, StageType.HAZARD) is not None
    assert registry.resolve(HazardType.WILDFIRE, StageType.HAZARD) is not None
    assert registry.resolve(HazardType.WILDFIRE, StageType.FIRE_REGIME) is not None

    with pytest.raises(NoCalculatorRegisteredError):
        registry.resolve(HazardType.FLOOD, StageType.FIRE_REGIME)
