"""``WorkflowTemplate`` aggregate (Domain Model §1/§6; Platform Architecture
§5) — the authoring side of the Workflow Engine, in the same "Assessment
Orchestration" bounded context as ``entities.Assessment``. A published
template is an immutable, versioned DAG of ``StageDefinition``s;
``Assessment.start_workflow`` binds to one specific template by id, and the
Workflow Engine (``application/workflow_engine.py``) reads it read-only to
decide what's runnable next. Nothing in this module ever touches
``Assessment`` — see that module's docstring for why.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from georisk.contexts.assessment.domain.errors import (
    CyclicWorkflowTemplateError,
    IllegalWorkflowTemplateStatusTransitionError,
    UnknownStagePredecessorError,
)
from georisk.contexts.assessment.domain.events import (
    WorkflowTemplateCreated,
    WorkflowTemplatePublished,
)
from georisk.contexts.assessment.domain.value_objects import HazardType
from georisk.contexts.assessment.domain.workflow_value_objects import (
    StageDefinition,
    StageExecutionStatus,
    StageType,
    WorkflowProgress,
    WorkflowTemplateStatus,
)
from georisk.shared_kernel.ids import TypedId


class WorkflowTemplateId(TypedId):
    pass


@dataclass(slots=True)
class WorkflowTemplate:
    id: WorkflowTemplateId
    hazard_type: HazardType
    name: str
    version: int
    status: WorkflowTemplateStatus
    stage_definitions: tuple[StageDefinition, ...]
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        hazard_type: HazardType,
        name: str,
        stage_definitions: tuple[StageDefinition, ...],
        version: int = 1,
    ) -> tuple[WorkflowTemplate, WorkflowTemplateCreated]:
        if not name.strip():
            raise ValueError("WorkflowTemplate name must not be blank")
        if not stage_definitions:
            raise ValueError("WorkflowTemplate must define at least one stage")

        template = cls(
            id=WorkflowTemplateId.new(),
            hazard_type=hazard_type,
            name=name,
            version=version,
            status=WorkflowTemplateStatus.DRAFT,
            stage_definitions=stage_definitions,
            created_at=datetime.now(UTC),
        )
        template._validate_dag()
        event = WorkflowTemplateCreated(
            workflow_template_id=str(template.id),
            hazard_type=hazard_type.value,
            name=name,
            version=version,
            stage_types=[sd.stage_type.value for sd in stage_definitions],
        )
        return template, event

    def _validate_dag(self) -> None:
        known = {sd.stage_type for sd in self.stage_definitions}
        for sd in self.stage_definitions:
            unknown = sd.required_predecessors - known
            if unknown:
                raise UnknownStagePredecessorError(
                    f"Stage {sd.stage_type} references unknown predecessor(s): "
                    f"{sorted(unknown, key=str)}"
                )

        # Kahn's algorithm: repeatedly "resolve" any stage whose
        # predecessors are all already resolved. A template whose graph
        # cannot be fully resolved this way contains a cycle.
        remaining = {sd.stage_type: set(sd.required_predecessors) for sd in self.stage_definitions}
        resolved: set[StageType] = set()
        progressed = True
        while remaining and progressed:
            progressed = False
            for stage_type, preds in list(remaining.items()):
                if preds <= resolved:
                    resolved.add(stage_type)
                    del remaining[stage_type]
                    progressed = True
        if remaining:
            raise CyclicWorkflowTemplateError(
                f"WorkflowTemplate has a cyclic dependency among: " f"{sorted(remaining, key=str)}"
            )

    def get_stage_definition(self, stage_type: StageType) -> StageDefinition | None:
        for sd in self.stage_definitions:
            if sd.stage_type == stage_type:
                return sd
        return None

    def required_stage_types(self) -> frozenset[StageType]:
        return frozenset(sd.stage_type for sd in self.stage_definitions)

    def runnable_stages(self, progress: WorkflowProgress) -> tuple[StageDefinition, ...]:
        """Stages that are NOT_STARTED (or FAILED, eligible for retry)
        whose predecessors are all COMPLETE per the given
        ``WorkflowProgress`` snapshot. Read-only — the Workflow Engine is
        responsible for actually dispatching these; this method only
        answers "what could run right now" (requirements #7 parallel /
        #8 sequential: a stage with no unmet predecessors is returned
        alongside every other such stage in the same call, which is what
        makes fan-out — Hazard || Exposure || Vulnerability — "parallel").
        """
        runnable = []
        for sd in self.stage_definitions:
            entry = progress.get(sd.stage_type)
            if entry.status not in (
                StageExecutionStatus.NOT_STARTED,
                StageExecutionStatus.FAILED,
            ):
                continue
            if progress.all_complete(sd.required_predecessors):
                runnable.append(sd)
        return tuple(runnable)

    def publish(self) -> WorkflowTemplatePublished:
        if self.status != WorkflowTemplateStatus.DRAFT:
            raise IllegalWorkflowTemplateStatusTransitionError(
                f"WorkflowTemplate {self.id} cannot be published from status {self.status}"
            )
        self.status = WorkflowTemplateStatus.PUBLISHED
        return WorkflowTemplatePublished(workflow_template_id=str(self.id))
