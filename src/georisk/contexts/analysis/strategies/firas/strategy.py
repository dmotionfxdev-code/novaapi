"""``FIRASHazardStrategy`` — implements ``contexts.analysis.domain.strategy
.HazardStrategy`` structurally (duck typing, no base class), binding the
five FIRAS calculators to their ``StageType``. This is the entire artifact
Sprint 5's "only a strategy registration should be required" test is
about: registering one instance of this class against ``HazardType.FLOOD``
in a ``StrategyRegistry`` (composition root, ``api/app.py``) is the only
platform-facing step — nothing in ``contexts.assessment``,
``contexts.assessment.application.workflow_engine``, or
``contexts.validation`` is touched to make FIRAS run end-to-end.
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.errors import NoCalculatorRegisteredError
from georisk.contexts.analysis.domain.strategy import StageCalculator
from georisk.contexts.analysis.domain.value_objects import StageType
from georisk.contexts.analysis.strategies.firas.exposure import FIRASExposureCalculator
from georisk.contexts.analysis.strategies.firas.hazard import FIRASHazardCalculator
from georisk.contexts.analysis.strategies.firas.resilience import FIRASResilienceCalculator
from georisk.contexts.analysis.strategies.firas.risk import FIRASRiskCalculator
from georisk.contexts.analysis.strategies.firas.vulnerability import FIRASVulnerabilityCalculator

_SUPPORTED_STAGES: frozenset[StageType] = frozenset(
    {
        StageType.HAZARD,
        StageType.EXPOSURE,
        StageType.VULNERABILITY,
        StageType.RISK,
        StageType.RESILIENCE,
    }
)

# Sprint 6: the declarative replacement for what used to be hardcoded
# directly in RecordStageResultHandler — see HazardStrategy
# .input_dependencies' docstring for why this moved here.
_INPUT_DEPENDENCIES: dict[StageType, dict[StageType, dict[str, str]]] = {
    StageType.RISK: {
        StageType.HAZARD: {"flood_hazard_index": "flood_hazard_index_input"},
        StageType.EXPOSURE: {"flood_exposure_index": "exposure_index_input"},
        StageType.VULNERABILITY: {"flood_insecurity_index": "flood_insecurity_index_input"},
    },
    StageType.RESILIENCE: {
        StageType.VULNERABILITY: {
            "cpc_score": "cpc_score",
            "ewe_score": "ewe_score",
            "kf_score": "kf_score",
            "dre_score": "dre_score",
            "rc_score": "rc_score",
        },
    },
}

_HISTORICAL_STAGES: frozenset[StageType] = frozenset(
    {StageType.VULNERABILITY, StageType.RESILIENCE}
)


class FIRASHazardStrategy:
    # Sprint 5.2 (GEORISK_SCOPE_REALIGNMENT.md §6): bumped from the
    # implicit Sprint 5 baseline ("1.0") because Risk/Vulnerability's
    # formulas changed in a way that alters computed results (additive ->
    # multiplicative Risk; equal-weight -> entropy-weighted Vulnerability).
    strategy_version = "firas-2.0"

    def __init__(self) -> None:
        self._calculators: dict[StageType, StageCalculator] = {
            StageType.HAZARD: FIRASHazardCalculator(),
            StageType.EXPOSURE: FIRASExposureCalculator(),
            StageType.VULNERABILITY: FIRASVulnerabilityCalculator(),
            StageType.RISK: FIRASRiskCalculator(),
            StageType.RESILIENCE: FIRASResilienceCalculator(),
        }

    def supported_stages(self) -> frozenset[StageType]:
        return _SUPPORTED_STAGES

    def get_calculator(self, stage_type: StageType) -> StageCalculator:
        calculator = self._calculators.get(stage_type)
        if calculator is None:
            raise NoCalculatorRegisteredError(
                f"FIRASHazardStrategy has no calculator for stage {stage_type}"
            )
        return calculator

    def input_dependencies(self, stage_type: StageType) -> dict[StageType, dict[str, str]]:
        return _INPUT_DEPENDENCIES.get(stage_type, {})

    def historical_stages(self) -> frozenset[StageType]:
        return _HISTORICAL_STAGES
