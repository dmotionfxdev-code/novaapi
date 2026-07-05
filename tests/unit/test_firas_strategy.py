"""Unit tests for ``FIRASHazardStrategy`` and ``StrategyRegistry`` — pure
logic, no I/O. Proves the registry's "callers never change to accommodate
a new registrant" property (Platform Architecture §6) structurally.
"""

from __future__ import annotations

import pytest

from georisk.contexts.analysis.application.strategy_registry import StrategyRegistry
from georisk.contexts.analysis.domain.errors import NoCalculatorRegisteredError
from georisk.contexts.analysis.domain.value_objects import HazardType, StageType
from georisk.contexts.analysis.strategies.firas.exposure import FIRASExposureCalculator
from georisk.contexts.analysis.strategies.firas.strategy import FIRASHazardStrategy

pytestmark = pytest.mark.unit


def test_supported_stages_covers_the_five_calculators() -> None:
    strategy = FIRASHazardStrategy()
    assert strategy.supported_stages() == {
        StageType.HAZARD,
        StageType.EXPOSURE,
        StageType.VULNERABILITY,
        StageType.RISK,
        StageType.RESILIENCE,
    }


def test_supported_stages_excludes_validation() -> None:
    """VALIDATION is a workflow stage but not a hazard-strategy stage —
    the Validation context (Sprint 4) owns it, not any HazardStrategy."""
    strategy = FIRASHazardStrategy()
    assert StageType.VALIDATION not in strategy.supported_stages()


def test_get_calculator_returns_the_right_type() -> None:
    strategy = FIRASHazardStrategy()
    assert isinstance(strategy.get_calculator(StageType.EXPOSURE), FIRASExposureCalculator)


def test_strategy_and_calculators_report_version_metadata() -> None:
    """Sprint 5.2: every calculator and the strategy itself carry a
    version tag — the mechanism ``StageResult.strategy_version``/
    ``formula_version`` records at compute time."""
    strategy = FIRASHazardStrategy()
    assert strategy.strategy_version == "firas-2.0"
    for stage_type in strategy.supported_stages():
        calculator = strategy.get_calculator(stage_type)
        assert isinstance(calculator.formula_version, str)
        assert calculator.formula_version


def test_get_calculator_raises_for_unsupported_stage() -> None:
    strategy = FIRASHazardStrategy()
    with pytest.raises(NoCalculatorRegisteredError):
        strategy.get_calculator(StageType.VALIDATION)


def test_registry_resolves_registered_hazard_type() -> None:
    registry = StrategyRegistry()
    registry.register(HazardType.FLOOD, FIRASHazardStrategy())
    calculator = registry.resolve(HazardType.FLOOD, StageType.HAZARD)
    assert calculator is not None


def test_registry_raises_for_unregistered_hazard_type() -> None:
    registry = StrategyRegistry()
    with pytest.raises(NoCalculatorRegisteredError, match="No HazardStrategy registered"):
        registry.resolve(HazardType.WILDFIRE, StageType.HAZARD)


def test_registry_raises_for_unsupported_stage_of_a_registered_strategy() -> None:
    registry = StrategyRegistry()
    registry.register(HazardType.FLOOD, FIRASHazardStrategy())
    with pytest.raises(NoCalculatorRegisteredError, match="does not support"):
        registry.resolve(HazardType.FLOOD, StageType.VALIDATION)


def test_registering_a_second_hazard_type_does_not_disturb_the_first() -> None:
    """The registry's core extensibility claim: adding a registrant is
    additive, never a branch anyone has to update."""
    registry = StrategyRegistry()
    registry.register(HazardType.FLOOD, FIRASHazardStrategy())

    class _StubWildfireStrategy:
        def supported_stages(self) -> frozenset[StageType]:
            return frozenset({StageType.HAZARD})

        def get_calculator(self, stage_type: StageType):  # noqa: ANN201
            return FIRASExposureCalculator()  # any stand-in calculator

    registry.register(HazardType.WILDFIRE, _StubWildfireStrategy())

    assert registry.resolve(HazardType.FLOOD, StageType.HAZARD) is not None
    assert registry.resolve(HazardType.WILDFIRE, StageType.HAZARD) is not None
