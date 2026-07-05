"""Repository-level integration tests against a real Postgres instance —
confirms the WorkflowTemplate domain<->ORM mapping round-trips correctly
(including the JSONB stage_definitions shape), and that Assessment's new
``workflow_template_id``/``workflow_progress`` fields persist and reload
correctly through the existing ``SqlAlchemyAssessmentRepository``.
"""

from __future__ import annotations

import pytest

from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.value_objects import HazardType
from georisk.contexts.assessment.domain.workflow_template import WorkflowTemplate
from georisk.contexts.assessment.domain.workflow_value_objects import (
    StageDefinition,
    StageExecutionStatus,
    StageType,
    TriggerMode,
    WorkflowTemplateStatus,
)
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.assessment.infrastructure.workflow_repositories import (
    SqlAlchemyWorkflowTemplateRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId, UserId

pytestmark = pytest.mark.integration


async def test_workflow_template_save_and_get_round_trips(db_session) -> None:  # noqa: ANN001
    template, _ = WorkflowTemplate.create(
        hazard_type=HazardType.FLOOD,
        name="Round Trip Template",
        stage_definitions=(
            StageDefinition(stage_type=StageType.HAZARD),
            StageDefinition(
                stage_type=StageType.RISK,
                required_predecessors=frozenset({StageType.HAZARD}),
                trigger_mode=TriggerMode.MANUAL,
                max_attempts=5,
            ),
        ),
    )
    repo = SqlAlchemyWorkflowTemplateRepository(db_session)
    await repo.save(template)
    await db_session.flush()

    fetched = await repo.get_by_id(template.id)
    assert fetched is not None
    assert fetched.name == "Round Trip Template"
    assert fetched.status == WorkflowTemplateStatus.DRAFT
    risk_def = fetched.get_stage_definition(StageType.RISK)
    assert risk_def is not None
    assert risk_def.required_predecessors == frozenset({StageType.HAZARD})
    assert risk_def.trigger_mode == TriggerMode.MANUAL
    assert risk_def.max_attempts == 5


async def test_workflow_template_publish_persists(db_session) -> None:  # noqa: ANN001
    template, _ = WorkflowTemplate.create(
        hazard_type=HazardType.WILDFIRE,
        name="Publishable",
        stage_definitions=(StageDefinition(stage_type=StageType.HAZARD),),
    )
    repo = SqlAlchemyWorkflowTemplateRepository(db_session)
    await repo.save(template)
    await db_session.flush()

    template.publish()
    await repo.save(template)
    await db_session.flush()

    fetched = await repo.get_by_id(template.id)
    assert fetched is not None
    assert fetched.status == WorkflowTemplateStatus.PUBLISHED


async def test_list_published_for_hazard_type_excludes_drafts(db_session) -> None:  # noqa: ANN001
    repo = SqlAlchemyWorkflowTemplateRepository(db_session)

    published, _ = WorkflowTemplate.create(
        hazard_type=HazardType.DROUGHT,
        name="Published One",
        stage_definitions=(StageDefinition(stage_type=StageType.HAZARD),),
    )
    published.publish()
    draft, _ = WorkflowTemplate.create(
        hazard_type=HazardType.DROUGHT,
        name="Still Draft",
        stage_definitions=(StageDefinition(stage_type=StageType.HAZARD),),
    )
    await repo.save(published)
    await repo.save(draft)
    await db_session.flush()

    results = await repo.list_published_for_hazard_type(HazardType.DROUGHT)
    names = {t.name for t in results}
    assert "Published One" in names
    assert "Still Draft" not in names


async def test_assessment_workflow_progress_round_trips(db_session) -> None:  # noqa: ANN001
    assessment, _ = Assessment.create(
        tenant_id=TenantId.new(),
        name="Workflow-bound Assessment",
        hazard_type=HazardType.FLOOD,
        created_by=UserId.new(),
    )
    assessment.mark_ready(changed_by="tester")
    assessment.start_workflow(
        workflow_template_id="11111111-1111-1111-1111-111111111111",
        stage_types=frozenset({StageType.HAZARD, StageType.EXPOSURE}),
        changed_by="tester",
    )
    assessment.start_stage(StageType.HAZARD, triggered_by="system:workflow-engine")
    assessment.complete_stage(
        StageType.HAZARD, stage_result_ref="stub:1", changed_by="system:workflow-engine"
    )

    repo = SqlAlchemyAssessmentRepository(db_session)
    await repo.save(assessment)
    await db_session.flush()

    fetched = await repo.get_by_id(assessment.id)
    assert fetched is not None
    assert fetched.workflow_template_id == "11111111-1111-1111-1111-111111111111"
    hazard_entry = fetched.workflow_progress.get(StageType.HAZARD)
    assert hazard_entry.status == StageExecutionStatus.COMPLETE
    assert hazard_entry.stage_result_ref == "stub:1"
    assert hazard_entry.completed_at is not None
    exposure_entry = fetched.workflow_progress.get(StageType.EXPOSURE)
    assert exposure_entry.status == StageExecutionStatus.NOT_STARTED
