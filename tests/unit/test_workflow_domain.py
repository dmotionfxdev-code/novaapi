"""Domain-layer unit tests for the Workflow Engine — pure logic, no I/O.
Exercises DAG validation (cycle/unknown-predecessor detection),
``WorkflowTemplate`` publication, the ``WorkflowProgress``/
``StageProgressEntry`` value objects' functional-update semantics, and
every workflow method ``Assessment`` gained this sprint.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.errors import (
    CyclicWorkflowTemplateError,
    IllegalAssessmentStatusTransitionError,
    IllegalStageExecutionTransitionError,
    IllegalWorkflowTemplateStatusTransitionError,
    UnknownStagePredecessorError,
    WorkflowNotCompleteError,
)
from georisk.contexts.assessment.domain.value_objects import HazardType
from georisk.contexts.assessment.domain.workflow_template import WorkflowTemplate
from georisk.contexts.assessment.domain.workflow_value_objects import (
    StageDefinition,
    StageExecutionStatus,
    StageProgressEntry,
    StageType,
    WorkflowProgress,
    WorkflowTemplateStatus,
)
from georisk.contexts.identity.domain.value_objects import TenantId, UserId

pytestmark = pytest.mark.unit


def _new_assessment() -> Assessment:
    assessment, _ = Assessment.create(
        tenant_id=TenantId.new(),
        name="Kigoma District Q3",
        hazard_type=HazardType.FLOOD,
        created_by=UserId.new(),
    )
    return assessment


def _parallel_then_sequential_stage_definitions() -> tuple[StageDefinition, ...]:
    """The Sprint 3 brief's worked example: Hazard || Exposure ||
    Vulnerability, then Risk, then Validation."""
    return (
        StageDefinition(stage_type=StageType.HAZARD),
        StageDefinition(stage_type=StageType.EXPOSURE),
        StageDefinition(stage_type=StageType.VULNERABILITY),
        StageDefinition(
            stage_type=StageType.RISK,
            required_predecessors=frozenset(
                {StageType.HAZARD, StageType.EXPOSURE, StageType.VULNERABILITY}
            ),
        ),
        StageDefinition(
            stage_type=StageType.VALIDATION, required_predecessors=frozenset({StageType.RISK})
        ),
    )


def _strictly_sequential_stage_definitions() -> tuple[StageDefinition, ...]:
    """The brief's other worked example: Hazard -> Exposure -> Vulnerability
    -> Risk, each depending only on its immediate predecessor."""
    return (
        StageDefinition(stage_type=StageType.HAZARD),
        StageDefinition(
            stage_type=StageType.EXPOSURE, required_predecessors=frozenset({StageType.HAZARD})
        ),
        StageDefinition(
            stage_type=StageType.VULNERABILITY,
            required_predecessors=frozenset({StageType.EXPOSURE}),
        ),
        StageDefinition(
            stage_type=StageType.RISK, required_predecessors=frozenset({StageType.VULNERABILITY})
        ),
    )


# --- StageDefinition ---------------------------------------------------


def test_stage_definition_rejects_self_dependency() -> None:
    with pytest.raises(ValueError, match="cannot depend on itself"):
        StageDefinition(
            stage_type=StageType.RISK, required_predecessors=frozenset({StageType.RISK})
        )


def test_stage_definition_rejects_non_positive_max_attempts() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        StageDefinition(stage_type=StageType.RISK, max_attempts=0)


# --- WorkflowTemplate: construction / DAG validation --------------------


def test_create_parallel_then_sequential_template_succeeds() -> None:
    template, event = WorkflowTemplate.create(
        hazard_type=HazardType.FLOOD,
        name="FIRAS Standard Flow",
        stage_definitions=_parallel_then_sequential_stage_definitions(),
    )
    assert template.status == WorkflowTemplateStatus.DRAFT
    assert template.version == 1
    assert len(template.stage_definitions) == 5
    assert event.workflow_template_id == str(template.id)
    assert set(event.stage_types) == {
        "HAZARD",
        "EXPOSURE",
        "VULNERABILITY",
        "RISK",
        "VALIDATION",
    }


def test_create_rejects_blank_name() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        WorkflowTemplate.create(
            hazard_type=HazardType.FLOOD,
            name="   ",
            stage_definitions=(StageDefinition(stage_type=StageType.HAZARD),),
        )


def test_create_rejects_empty_stage_definitions() -> None:
    with pytest.raises(ValueError, match="at least one stage"):
        WorkflowTemplate.create(hazard_type=HazardType.FLOOD, name="Empty", stage_definitions=())


def test_create_rejects_unknown_predecessor() -> None:
    with pytest.raises(UnknownStagePredecessorError):
        WorkflowTemplate.create(
            hazard_type=HazardType.FLOOD,
            name="Broken",
            stage_definitions=(
                StageDefinition(
                    stage_type=StageType.RISK,
                    required_predecessors=frozenset({StageType.HAZARD}),
                ),
            ),
        )


def test_create_rejects_cyclic_dependency() -> None:
    with pytest.raises(CyclicWorkflowTemplateError):
        WorkflowTemplate.create(
            hazard_type=HazardType.FLOOD,
            name="Cyclic",
            stage_definitions=(
                StageDefinition(
                    stage_type=StageType.HAZARD,
                    required_predecessors=frozenset({StageType.EXPOSURE}),
                ),
                StageDefinition(
                    stage_type=StageType.EXPOSURE,
                    required_predecessors=frozenset({StageType.HAZARD}),
                ),
            ),
        )


# --- WorkflowTemplate: publish -------------------------------------------


def test_publish_transitions_draft_to_published() -> None:
    template, _ = WorkflowTemplate.create(
        hazard_type=HazardType.FLOOD,
        name="Publishable",
        stage_definitions=(StageDefinition(stage_type=StageType.HAZARD),),
    )
    event = template.publish()
    assert template.status == WorkflowTemplateStatus.PUBLISHED
    assert event.workflow_template_id == str(template.id)


def test_publish_twice_is_illegal() -> None:
    template, _ = WorkflowTemplate.create(
        hazard_type=HazardType.FLOOD,
        name="Publishable",
        stage_definitions=(StageDefinition(stage_type=StageType.HAZARD),),
    )
    template.publish()
    with pytest.raises(IllegalWorkflowTemplateStatusTransitionError):
        template.publish()


# --- WorkflowTemplate: runnable_stages (parallel + sequential) ----------


def test_runnable_stages_fans_out_in_parallel_when_no_predecessors_are_shared() -> None:
    template, _ = WorkflowTemplate.create(
        hazard_type=HazardType.FLOOD,
        name="Parallel Flow",
        stage_definitions=_parallel_then_sequential_stage_definitions(),
    )
    runnable = {sd.stage_type for sd in template.runnable_stages(WorkflowProgress())}
    assert runnable == {StageType.HAZARD, StageType.EXPOSURE, StageType.VULNERABILITY}


def test_runnable_stages_waits_for_all_parallel_predecessors_before_risk() -> None:
    template, _ = WorkflowTemplate.create(
        hazard_type=HazardType.FLOOD,
        name="Parallel Flow",
        stage_definitions=_parallel_then_sequential_stage_definitions(),
    )
    now = datetime.now(UTC)
    progress = WorkflowProgress().initialize(str(template.id), template.required_stage_types())
    # Only two of the three parallel predecessors complete -> Risk still blocked.
    progress = progress.with_entry(
        StageProgressEntry(stage_type=StageType.HAZARD)
        .advance_to(StageExecutionStatus.RUNNING, now=now)
        .advance_to(StageExecutionStatus.COMPLETE, now=now)
    )
    progress = progress.with_entry(
        StageProgressEntry(stage_type=StageType.EXPOSURE)
        .advance_to(StageExecutionStatus.RUNNING, now=now)
        .advance_to(StageExecutionStatus.COMPLETE, now=now)
    )
    runnable = {sd.stage_type for sd in template.runnable_stages(progress)}
    assert StageType.RISK not in runnable

    # The third completes -> Risk (and only Risk) becomes runnable.
    progress = progress.with_entry(
        StageProgressEntry(stage_type=StageType.VULNERABILITY)
        .advance_to(StageExecutionStatus.RUNNING, now=now)
        .advance_to(StageExecutionStatus.COMPLETE, now=now)
    )
    runnable = {sd.stage_type for sd in template.runnable_stages(progress)}
    assert runnable == {StageType.RISK}


def test_runnable_stages_enforces_strict_sequential_chain() -> None:
    template, _ = WorkflowTemplate.create(
        hazard_type=HazardType.FLOOD,
        name="Sequential Flow",
        stage_definitions=_strictly_sequential_stage_definitions(),
    )
    progress = WorkflowProgress().initialize(str(template.id), template.required_stage_types())
    runnable = {sd.stage_type for sd in template.runnable_stages(progress)}
    assert runnable == {StageType.HAZARD}


# --- StageProgressEntry / WorkflowProgress -------------------------------


def test_stage_progress_entry_transitions_and_attempt_counting() -> None:
    entry = StageProgressEntry(stage_type=StageType.HAZARD)
    now = datetime.now(UTC)

    running = entry.advance_to(StageExecutionStatus.RUNNING, now=now)
    assert running.status == StageExecutionStatus.RUNNING
    assert running.attempt_count == 1
    assert running.started_at == now

    failed = running.advance_to(StageExecutionStatus.FAILED, now=now, error="boom")
    assert failed.status == StageExecutionStatus.FAILED
    assert failed.last_error == "boom"

    retried = failed.advance_to(StageExecutionStatus.RUNNING, now=now)
    assert retried.attempt_count == 2
    assert retried.last_error is None

    completed = retried.advance_to(
        StageExecutionStatus.COMPLETE, now=now, stage_result_ref="stub:abc"
    )
    assert completed.status == StageExecutionStatus.COMPLETE
    assert completed.stage_result_ref == "stub:abc"


def test_stage_progress_entry_rejects_illegal_transition() -> None:
    entry = StageProgressEntry(stage_type=StageType.HAZARD)
    with pytest.raises(ValueError, match="cannot transition"):
        entry.advance_to(StageExecutionStatus.COMPLETE, now=datetime.now(UTC))


def test_workflow_progress_get_returns_not_started_default() -> None:
    progress = WorkflowProgress()
    entry = progress.get(StageType.HAZARD)
    assert entry.status == StageExecutionStatus.NOT_STARTED
    assert entry.attempt_count == 0


def test_workflow_progress_with_entry_replaces_not_duplicates() -> None:
    progress = WorkflowProgress()
    now = datetime.now(UTC)
    running = StageProgressEntry(stage_type=StageType.HAZARD).advance_to(
        StageExecutionStatus.RUNNING, now=now
    )
    progress = progress.with_entry(running)
    assert len(progress.entries) == 1

    completed = running.advance_to(StageExecutionStatus.COMPLETE, now=now)
    progress = progress.with_entry(completed)
    assert len(progress.entries) == 1
    assert progress.get(StageType.HAZARD).status == StageExecutionStatus.COMPLETE


def test_workflow_progress_all_complete() -> None:
    now = datetime.now(UTC)
    progress = WorkflowProgress()
    progress = progress.with_entry(
        StageProgressEntry(stage_type=StageType.HAZARD)
        .advance_to(StageExecutionStatus.RUNNING, now=now)
        .advance_to(StageExecutionStatus.COMPLETE, now=now)
    )
    assert progress.all_complete(frozenset({StageType.HAZARD})) is True
    assert progress.all_complete(frozenset({StageType.HAZARD, StageType.EXPOSURE})) is False


# --- Assessment workflow methods ------------------------------------------


def _ready_assessment() -> Assessment:
    assessment = _new_assessment()
    assessment.mark_ready(changed_by="analyst-1")
    return assessment


def test_start_workflow_binds_template_and_initializes_progress() -> None:
    assessment = _ready_assessment()
    stage_types = frozenset({StageType.HAZARD, StageType.EXPOSURE})
    transition_event, started_event = assessment.start_workflow(
        workflow_template_id="template-1", stage_types=stage_types, changed_by="analyst-1"
    )
    assert assessment.status.value == "RUNNING"
    assert assessment.workflow_template_id == "template-1"
    assert transition_event.to_status == "RUNNING"
    assert set(started_event.stage_types) == {"HAZARD", "EXPOSURE"}
    for st in stage_types:
        assert assessment.workflow_progress.get(st).status == StageExecutionStatus.NOT_STARTED


def test_start_workflow_illegal_from_draft() -> None:
    assessment = _new_assessment()
    with pytest.raises(IllegalAssessmentStatusTransitionError):
        assessment.start_workflow(
            workflow_template_id="template-1",
            stage_types=frozenset({StageType.HAZARD}),
            changed_by="analyst-1",
        )


def test_start_stage_requires_running_assessment() -> None:
    assessment = _ready_assessment()  # READY, not RUNNING
    with pytest.raises(IllegalAssessmentStatusTransitionError):
        assessment.start_stage(StageType.HAZARD, triggered_by="analyst-1")


def test_start_stage_then_complete_stage_happy_path() -> None:
    assessment = _ready_assessment()
    assessment.start_workflow(
        workflow_template_id="template-1",
        stage_types=frozenset({StageType.HAZARD}),
        changed_by="analyst-1",
    )
    started = assessment.start_stage(StageType.HAZARD, triggered_by="system:workflow-engine")
    assert started.attempt == 1
    assert assessment.workflow_progress.get(StageType.HAZARD).status == StageExecutionStatus.RUNNING

    completed = assessment.complete_stage(
        StageType.HAZARD, stage_result_ref="stub:xyz", changed_by="system:workflow-engine"
    )
    assert completed.stage_result_ref == "stub:xyz"
    assert assessment.workflow_progress.is_complete(StageType.HAZARD)


def test_complete_stage_before_start_is_illegal() -> None:
    assessment = _ready_assessment()
    assessment.start_workflow(
        workflow_template_id="template-1",
        stage_types=frozenset({StageType.HAZARD}),
        changed_by="analyst-1",
    )
    with pytest.raises(IllegalStageExecutionTransitionError):
        assessment.complete_stage(StageType.HAZARD, stage_result_ref=None, changed_by="analyst-1")


def test_fail_stage_records_error_and_allows_retry_via_start_stage() -> None:
    assessment = _ready_assessment()
    assessment.start_workflow(
        workflow_template_id="template-1",
        stage_types=frozenset({StageType.HAZARD}),
        changed_by="analyst-1",
    )
    assessment.start_stage(StageType.HAZARD, triggered_by="system:workflow-engine")
    failed = assessment.fail_stage(
        StageType.HAZARD, error="stub failure", changed_by="system:workflow-engine"
    )
    assert failed.error == "stub failure"
    assert assessment.workflow_progress.get(StageType.HAZARD).status == StageExecutionStatus.FAILED

    retried = assessment.start_stage(StageType.HAZARD, triggered_by="system:workflow-engine")
    assert retried.attempt == 2


def test_advance_past_running_blocked_until_all_required_stages_complete() -> None:
    assessment = _ready_assessment()
    stage_types = frozenset({StageType.HAZARD, StageType.EXPOSURE})
    assessment.start_workflow(
        workflow_template_id="template-1", stage_types=stage_types, changed_by="analyst-1"
    )
    assessment.start_stage(StageType.HAZARD, triggered_by="system:workflow-engine")
    assessment.complete_stage(
        StageType.HAZARD, stage_result_ref=None, changed_by="system:workflow-engine"
    )

    with pytest.raises(WorkflowNotCompleteError):
        assessment.advance_past_running(required_stage_types=stage_types, changed_by="analyst-1")

    assessment.start_stage(StageType.EXPOSURE, triggered_by="system:workflow-engine")
    assessment.complete_stage(
        StageType.EXPOSURE, stage_result_ref=None, changed_by="system:workflow-engine"
    )

    event = assessment.advance_past_running(
        required_stage_types=stage_types, changed_by="analyst-1"
    )
    assert assessment.status.value == "VALIDATED"
    assert event.to_status == "VALIDATED"
