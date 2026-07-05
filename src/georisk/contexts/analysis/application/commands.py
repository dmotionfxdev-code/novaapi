"""Command DTO (Application Layer §1). ``RecordStageResultCommand`` is this
context's equivalent of Sprint 4's ``RunValidationCommand`` — issued by the
composition-root ``AnalysisStageExecutor`` (``api/analysis_stage_executor
.py``) whenever Assessment's Workflow Engine calls ``ExecuteStageCommand``
for a hazard-strategy stage, never by ``contexts.assessment`` directly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecordStageResultCommand:
    tenant_id: str
    assessment_id: str
    hazard_type: str
    stage_type: str
    issued_by: str
