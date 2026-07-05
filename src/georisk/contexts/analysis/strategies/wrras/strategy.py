"""``WRRASHazardStrategy`` — Sprint 6: the second independent proof of
Platform Architecture §6's "hazard type is a strategy registration, not a
platform change" claim. Binds five core calculators (Hazard, Exposure,
Vulnerability [with Insecurity folded in], Risk, Resilience) plus three
optional, non-gating supporting-analysis calculators (Fire Regime, Burn
Occurrence Probability, Burn Severity — ``WRRAS_SCOPE_DECISION_LOG.md``)
to their ``StageType``. Registering one instance of this class against
``HazardType.WILDFIRE`` in a ``StrategyRegistry`` (composition root,
``api/app.py``) is the only platform-facing step required.
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.errors import NoCalculatorRegisteredError
from georisk.contexts.analysis.domain.strategy import StageCalculator
from georisk.contexts.analysis.domain.value_objects import StageType
from georisk.contexts.analysis.strategies.wrras.burn_probability import (
    WRRASBurnProbabilityCalculator,
)
from georisk.contexts.analysis.strategies.wrras.burn_severity import WRRASBurnSeverityCalculator
from georisk.contexts.analysis.strategies.wrras.exposure import WRRASExposureCalculator
from georisk.contexts.analysis.strategies.wrras.fire_regime import WRRASFireRegimeCalculator
from georisk.contexts.analysis.strategies.wrras.hazard import WRRASHazardCalculator
from georisk.contexts.analysis.strategies.wrras.resilience import WRRASResilienceCalculator
from georisk.contexts.analysis.strategies.wrras.risk import WRRASRiskCalculator
from georisk.contexts.analysis.strategies.wrras.vulnerability import WRRASVulnerabilityCalculator

_SUPPORTED_STAGES: frozenset[StageType] = frozenset(
    {
        StageType.HAZARD,
        StageType.EXPOSURE,
        StageType.VULNERABILITY,
        StageType.RISK,
        StageType.RESILIENCE,
        # Optional, non-gating supporting-analysis stages
        # (WRRAS_SCOPE_DECISION_LOG.md) — never a required_predecessor of
        # anything in a WorkflowTemplate; an assessment reaches VALIDATED
        # with or without them.
        StageType.FIRE_REGIME,
        StageType.BURN_OCCURRENCE_PROBABILITY,
        StageType.BURN_SEVERITY,
    }
)

# The declarative replacement for what Sprint 5 originally hardcoded in
# RecordStageResultHandler — see HazardStrategy.input_dependencies'
# docstring. Note WRRAS's RISK depends on VULNERABILITY directly (not an
# insecurity index, unlike FIRAS) — WRRAS_ARCHITECTURE_ALIGNMENT.md §1.1's
# named structural difference.
_INPUT_DEPENDENCIES: dict[StageType, dict[StageType, dict[str, str]]] = {
    StageType.RISK: {
        StageType.HAZARD: {"wildfire_hazard_index": "wildfire_hazard_index_input"},
        StageType.EXPOSURE: {"wildfire_exposure_index": "wildfire_exposure_index_input"},
        StageType.VULNERABILITY: {
            "wildfire_vulnerability_index": "wildfire_vulnerability_index_input"
        },
    },
    StageType.RESILIENCE: {
        StageType.VULNERABILITY: {
            "cpc_score": "cpc_score",
            "ewe_score": "ewe_score",
            "wki_score": "wki_score",
            "ere_score": "ere_score",
            "rc_score": "rc_score",
        },
    },
}

# WRRAS uses no EWM anywhere (WRRAS_ARCHITECTURE_ALIGNMENT.md §2/§4,
# confirmed by grepping every legacy formula module) — unlike FIRAS,
# nothing here ever needs historical comparison data.
_HISTORICAL_STAGES: frozenset[StageType] = frozenset()


class WRRASHazardStrategy:
    strategy_version = "wrras-1.0"

    def __init__(self) -> None:
        self._calculators: dict[StageType, StageCalculator] = {
            StageType.HAZARD: WRRASHazardCalculator(),
            StageType.EXPOSURE: WRRASExposureCalculator(),
            StageType.VULNERABILITY: WRRASVulnerabilityCalculator(),
            StageType.RISK: WRRASRiskCalculator(),
            StageType.RESILIENCE: WRRASResilienceCalculator(),
            StageType.FIRE_REGIME: WRRASFireRegimeCalculator(),
            StageType.BURN_OCCURRENCE_PROBABILITY: WRRASBurnProbabilityCalculator(),
            StageType.BURN_SEVERITY: WRRASBurnSeverityCalculator(),
        }

    def supported_stages(self) -> frozenset[StageType]:
        return _SUPPORTED_STAGES

    def get_calculator(self, stage_type: StageType) -> StageCalculator:
        calculator = self._calculators.get(stage_type)
        if calculator is None:
            raise NoCalculatorRegisteredError(
                f"WRRASHazardStrategy has no calculator for stage {stage_type}"
            )
        return calculator

    def input_dependencies(self, stage_type: StageType) -> dict[StageType, dict[str, str]]:
        return _INPUT_DEPENDENCIES.get(stage_type, {})

    def historical_stages(self) -> frozenset[StageType]:
        return _HISTORICAL_STAGES
