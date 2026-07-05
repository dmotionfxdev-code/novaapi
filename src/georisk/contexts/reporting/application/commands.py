from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GenerateReportCommand:
    tenant_id: str
    assessment_id: str
    issued_by: str


@dataclass(frozen=True, slots=True)
class FinalizeReportCommand:
    tenant_id: str
    report_id: str
    finalized_by: str
