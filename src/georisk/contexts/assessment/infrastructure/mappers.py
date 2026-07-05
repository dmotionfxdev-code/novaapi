"""Maps between the Assessment/WorkflowTemplate domain entities and their
SQLAlchemy ORM representations. Free functions, not methods on either side,
so neither layer needs to know about the other's existence (same pattern as
Identity, Sprint 1).
"""

from __future__ import annotations

from datetime import datetime

from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.value_objects import (
    AssessmentId,
    AssessmentStatus,
    HazardType,
)
from georisk.contexts.assessment.domain.workflow_template import (
    WorkflowTemplate,
    WorkflowTemplateId,
)
from georisk.contexts.assessment.domain.workflow_value_objects import (
    StageDefinition,
    StageExecutionStatus,
    StageProgressEntry,
    StageType,
    TriggerMode,
    WorkflowProgress,
    WorkflowTemplateStatus,
)
from georisk.contexts.assessment.infrastructure.models import AssessmentModel, WorkflowTemplateModel
from georisk.contexts.identity.domain.value_objects import TenantId, UserId


def _progress_to_json(progress: WorkflowProgress) -> dict:
    return {
        "workflow_template_id": progress.workflow_template_id,
        "entries": [
            {
                "stage_type": e.stage_type.value,
                "status": e.status.value,
                "attempt_count": e.attempt_count,
                "stage_result_ref": e.stage_result_ref,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "completed_at": e.completed_at.isoformat() if e.completed_at else None,
                "last_error": e.last_error,
            }
            for e in progress.entries
        ],
    }


def _progress_from_json(data: dict) -> WorkflowProgress:
    return WorkflowProgress(
        workflow_template_id=data.get("workflow_template_id"),
        entries=tuple(
            StageProgressEntry(
                stage_type=StageType(e["stage_type"]),
                status=StageExecutionStatus(e["status"]),
                attempt_count=e["attempt_count"],
                stage_result_ref=e.get("stage_result_ref"),
                started_at=(
                    datetime.fromisoformat(e["started_at"]) if e.get("started_at") else None
                ),
                completed_at=(
                    datetime.fromisoformat(e["completed_at"]) if e.get("completed_at") else None
                ),
                last_error=e.get("last_error"),
            )
            for e in data.get("entries", [])
        ),
    )


def assessment_to_domain(model: AssessmentModel) -> Assessment:
    return Assessment(
        id=AssessmentId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        name=model.name,
        hazard_type=HazardType(model.hazard_type),
        status=AssessmentStatus(model.status),
        created_by=UserId(value=model.created_by),
        created_at=model.created_at,
        updated_at=model.updated_at,
        cancellation_reason=model.cancellation_reason,
        version=model.version,
        workflow_template_id=str(model.workflow_template_id)
        if model.workflow_template_id
        else None,
        workflow_progress=_progress_from_json(model.workflow_progress or {}),
    )


def apply_assessment_to_model(entity: Assessment, model: AssessmentModel) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.name = entity.name
    model.hazard_type = entity.hazard_type.value
    model.status = entity.status.value
    model.created_by = entity.created_by.value
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at
    model.cancellation_reason = entity.cancellation_reason
    model.workflow_template_id = (
        WorkflowTemplateId.from_string(entity.workflow_template_id).value
        if entity.workflow_template_id
        else None
    )
    model.workflow_progress = _progress_to_json(entity.workflow_progress)


def workflow_template_to_domain(model: WorkflowTemplateModel) -> WorkflowTemplate:
    return WorkflowTemplate(
        id=WorkflowTemplateId(value=model.id),
        hazard_type=HazardType(model.hazard_type),
        name=model.name,
        version=model.version,
        status=WorkflowTemplateStatus(model.status),
        stage_definitions=tuple(
            StageDefinition(
                stage_type=StageType(sd["stage_type"]),
                required_predecessors=frozenset(
                    StageType(p) for p in sd.get("required_predecessors", [])
                ),
                trigger_mode=TriggerMode(sd.get("trigger_mode", "AUTOMATIC")),
                max_attempts=sd.get("max_attempts", 3),
            )
            for sd in model.stage_definitions
        ),
        created_at=model.created_at,
    )


def apply_workflow_template_to_model(
    entity: WorkflowTemplate, model: WorkflowTemplateModel
) -> None:
    model.id = entity.id.value
    model.hazard_type = entity.hazard_type.value
    model.name = entity.name
    model.version = entity.version
    model.status = entity.status.value
    model.stage_definitions = [
        {
            "stage_type": sd.stage_type.value,
            "required_predecessors": sorted(p.value for p in sd.required_predecessors),
            "trigger_mode": sd.trigger_mode.value,
            "max_attempts": sd.max_attempts,
        }
        for sd in entity.stage_definitions
    ]
    model.created_at = entity.created_at
