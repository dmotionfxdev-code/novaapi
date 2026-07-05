"""Prediction domain events — appended to the outbox within the same
transaction as the ``PredictionRun`` they describe (Sprint 8 requirement
#8 — Audit Events; matching every prior context's pattern).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class PredictionRunCompleted:
    event_type: ClassVar[str] = "prediction.PredictionRunCompleted"
    prediction_run_id: str
    tenant_id: str
    assessment_id: str
    method: str
    version: int
    formula_version: str
    sample_size: int

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class PredictionRunFailed:
    event_type: ClassVar[str] = "prediction.PredictionRunFailed"
    prediction_run_id: str
    tenant_id: str
    assessment_id: str
    method: str
    version: int
    error: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}
