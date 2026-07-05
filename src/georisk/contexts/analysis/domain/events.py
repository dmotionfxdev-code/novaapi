"""Analysis Engine domain events — appended to the outbox within the same
transaction as the ``StageResult`` they describe (Sprint 5 brief's
"Emit StageResultComputed events" requirement). Named to match the
Application Layer's own worked trace (``StageResultComputed`` fires after
every successful compute; the Workflow Engine reacts to it by issuing
``RecordStageCompletion`` against Assessment — composition-root glue, not
this module, per "Validation/Analysis never mutates Assessment directly").
``StageResultFailed`` is this module's counterpart for the execution-error
path, the same shape Sprint 4 gave ``ValidationRunErrored``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class StageResultComputed:
    event_type: ClassVar[str] = "analysis.StageResultComputed"
    stage_result_id: str
    tenant_id: str
    assessment_id: str
    hazard_type: str
    stage_type: str
    version: int
    confidence_tier: str
    indicators: dict
    strategy_version: str
    formula_version: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class StageResultFailed:
    event_type: ClassVar[str] = "analysis.StageResultFailed"
    stage_result_id: str
    tenant_id: str
    assessment_id: str
    hazard_type: str
    stage_type: str
    version: int
    error: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}
