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


@dataclass(frozen=True, slots=True)
class GenerateRiskLayerCommand:
    """Sprint C. ``features``/``geometry_type``/``crs`` are already
    resolved, plain-GeoJSON-shaped data by the time this command is
    issued — resolving them requires reading Data Acquisition's real
    Shapefile-sourced ``Dataset``/``AcquisitionJob``, which only the
    composition root (``api/risk_layer_ports.py``) may do; this handler
    never imports ``contexts.data_acquisition`` itself.
    """

    tenant_id: str
    assessment_id: str
    stage_result_id: str
    dataset_id: str
    geometry_type: str
    crs: str
    features: list[dict]
    issued_by: str
