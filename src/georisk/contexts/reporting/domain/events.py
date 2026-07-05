"""Reporting domain events — appended to the outbox within the same
transaction as the ``Report`` they describe (Sprint 9 requirement: Audit
Events; matching every prior context's pattern). Names match Domain Model
§1 row 15 / §5's event table (``ReportFinalized``) where one already
exists; ``ReportGenerated``/``ReportGenerationFailed`` are this context's
own, following the ``Completed``/``Failed`` pair convention every prior
sprint's aggregate already uses.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class ReportGenerated:
    event_type: ClassVar[str] = "reporting.ReportGenerated"
    report_id: str
    tenant_id: str
    assessment_id: str
    version: int
    hazard_type: str
    has_risk_summary: bool
    has_prediction_summary: bool
    has_validation_summary: bool
    dataset_count: int

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class ReportFinalized:
    event_type: ClassVar[str] = "reporting.ReportFinalized"
    report_id: str
    tenant_id: str
    assessment_id: str
    version: int
    finalized_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class ReportGenerationFailed:
    event_type: ClassVar[str] = "reporting.ReportGenerationFailed"
    report_id: str
    tenant_id: str
    assessment_id: str
    version: int
    error: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}
