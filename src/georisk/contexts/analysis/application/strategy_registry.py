"""``StrategyRegistry`` — Platform Architecture §6: "the single lookup
every ``ExecuteStage`` command handler calls... New hazard types register
with this lookup at platform startup; the registry's callers — the
command handler, the Workflow Engine, the API layer — never change to
accommodate a new registrant." This is the mechanical embodiment of
"hazard type is a strategy lookup, not an application," and the entire
reason Sprint 5's success test ("only a strategy registration should be
required") is achievable: `api/app.py` calls ``registry.register(FLOOD,
FIRASHazardStrategy())`` once at startup; everything below this class
(the command handler) is written against the registry, never against
``FIRASHazardStrategy`` by name.
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.errors import NoCalculatorRegisteredError
from georisk.contexts.analysis.domain.strategy import HazardStrategy, StageCalculator
from georisk.contexts.analysis.domain.value_objects import HazardType, StageType


class StrategyRegistry:
    def __init__(self) -> None:
        self._strategies: dict[HazardType, HazardStrategy] = {}

    def register(self, hazard_type: HazardType, strategy: HazardStrategy) -> None:
        self._strategies[hazard_type] = strategy

    def get_strategy(self, hazard_type: HazardType) -> HazardStrategy:
        """Fetches the whole registered strategy object — used when a
        caller (``RecordStageResultHandler``, Sprint 5.2) needs the
        strategy's own ``strategy_version`` alongside a calculator, not
        just the calculator itself."""
        strategy = self._strategies.get(hazard_type)
        if strategy is None:
            raise NoCalculatorRegisteredError(
                f"No HazardStrategy registered for hazard type {hazard_type}"
            )
        return strategy

    def resolve(self, hazard_type: HazardType, stage_type: StageType) -> StageCalculator:
        strategy = self.get_strategy(hazard_type)
        if stage_type not in strategy.supported_stages():
            raise NoCalculatorRegisteredError(
                f"HazardStrategy for {hazard_type} does not support stage {stage_type}"
            )
        return strategy.get_calculator(stage_type)
