"""End-to-end proof that Validation integrates with the Workflow Engine as
a real stage (Sprint 4 brief's core requirement) — driven through the
actual `WorkflowEngine` + `CompositeStageExecutor` + `ValidationStageExecutor`
composition, against a real Postgres instance, not mocked.

Uses the ``real_database`` fixture (a genuine, independently-connecting
``Database``), the same reasoning as Sprint 3's workflow-engine tests: both
`WorkflowEngine` and `ValidationStageExecutor` open several of their own
sequential transactions per call.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from georisk.api.workflow_stage_executors import CompositeStageExecutor, ValidationStageExecutor
from georisk.contexts.assessment.application.workflow_engine import (
    ImmediateSuccessStageExecutor,
    WorkflowEngine,
)
from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.value_objects import HazardType
from georisk.contexts.assessment.domain.workflow_template import WorkflowTemplate
from georisk.contexts.assessment.domain.workflow_value_objects import StageDefinition, StageType
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.assessment.infrastructure.workflow_repositories import (
    SqlAlchemyWorkflowTemplateRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.contexts.validation.domain.value_objects import ValidationDataset
from georisk.contexts.validation.infrastructure.models import ValidationRunModel
from georisk.db.session import Database

pytestmark = pytest.mark.integration


class _AlwaysErrorsResolver:
    async def resolve(self, *, subject_id, subject_type, assessment_id):  # noqa: ANN001, ARG002
        raise RuntimeError("ground truth source unavailable")


class _FlakyResolver:
    """Fails the first ``fail_times`` calls, then returns a fixed dataset —
    exercises the Workflow Engine's retry mechanism (Sprint 3) through
    Validation's own resolution seam."""

    def __init__(self, fail_times: int) -> None:
        self._fail_times = fail_times
        self._attempts = 0

    async def resolve(self, *, subject_id, subject_type, assessment_id):  # noqa: ANN001, ARG002
        if self._attempts < self._fail_times:
            self._attempts += 1
            raise RuntimeError("transient resolver failure")
        return ValidationDataset(
            y_true=("POSITIVE", "NEGATIVE"),
            y_pred=("POSITIVE", "NEGATIVE"),
            labels=("NEGATIVE", "POSITIVE"),
        )


def _hazard_risk_validation_template() -> tuple[StageDefinition, ...]:
    return (
        StageDefinition(stage_type=StageType.HAZARD),
        StageDefinition(
            stage_type=StageType.RISK, required_predecessors=frozenset({StageType.HAZARD})
        ),
        StageDefinition(
            stage_type=StageType.VALIDATION, required_predecessors=frozenset({StageType.RISK})
        ),
    )


async def _create_published_template(db: Database, *, hazard_type: HazardType) -> WorkflowTemplate:
    async with db.session() as session:
        template, _ = WorkflowTemplate.create(
            hazard_type=hazard_type,
            name=f"Validation Integration Template {uuid.uuid4().hex[:8]}",
            stage_definitions=_hazard_risk_validation_template(),
        )
        template.publish()
        await SqlAlchemyWorkflowTemplateRepository(session).save(template)
        await session.commit()
    return template


async def _create_ready_assessment(db: Database, *, hazard_type: HazardType) -> Assessment:
    tenant_id = TenantId.new()
    async with db.session() as session:
        assessment, _ = Assessment.create(
            tenant_id=tenant_id,
            name=f"Validation Integration Assessment {uuid.uuid4().hex[:8]}",
            hazard_type=hazard_type,
            created_by=UserId.new(),
        )
        assessment.mark_ready(changed_by="tester")
        await SqlAlchemyAssessmentRepository(session).save(assessment)
        await session.commit()
    return assessment


async def _reload_assessment(db: Database, assessment: Assessment) -> Assessment:
    async with db.session() as session:
        reloaded = await SqlAlchemyAssessmentRepository(session).get_by_id(assessment.id)
        assert reloaded is not None
        return reloaded


async def test_validation_stage_runs_via_workflow_engine_and_advances_assessment(
    real_database: Database,
) -> None:
    template = await _create_published_template(real_database, hazard_type=HazardType.FLOOD)
    assessment = await _create_ready_assessment(real_database, hazard_type=HazardType.FLOOD)

    executor = CompositeStageExecutor(
        default=ImmediateSuccessStageExecutor(),
        overrides={StageType.VALIDATION: ValidationStageExecutor(real_database)},
    )
    engine = WorkflowEngine(real_database, executor)
    await engine.start_workflow(
        tenant_id=str(assessment.tenant_id),
        assessment_id=str(assessment.id),
        workflow_template_id=str(template.id),
        actor="analyst-1",
    )

    final = await _reload_assessment(real_database, assessment)
    assert final.status.value == "VALIDATED"
    validation_entry = final.workflow_progress.get(StageType.VALIDATION)
    assert validation_entry.status.value == "COMPLETE"
    assert validation_entry.stage_result_ref is not None

    # The ValidationRun really was persisted, referencing the RISK stage's
    # stub stage_result_ref as its subject (Assessment read, not mutated).
    risk_ref = final.workflow_progress.get(StageType.RISK).stage_result_ref
    async with real_database.session() as session:
        result = await session.execute(
            select(ValidationRunModel).where(
                ValidationRunModel.assessment_id == uuid.UUID(str(final.id))
            )
        )
        run_model = result.scalar_one()
    assert run_model.subject_id == risk_ref
    assert run_model.status == "COMPLETED"


async def test_validation_stage_failure_triggers_workflow_engine_retry(
    real_database: Database,
) -> None:
    template = await _create_published_template(real_database, hazard_type=HazardType.WILDFIRE)
    assessment = await _create_ready_assessment(real_database, hazard_type=HazardType.WILDFIRE)

    executor = CompositeStageExecutor(
        default=ImmediateSuccessStageExecutor(),
        overrides={
            StageType.VALIDATION: ValidationStageExecutor(
                real_database, resolver=_FlakyResolver(fail_times=2)
            )
        },
    )
    engine = WorkflowEngine(real_database, executor)
    await engine.start_workflow(
        tenant_id=str(assessment.tenant_id),
        assessment_id=str(assessment.id),
        workflow_template_id=str(template.id),
        actor="analyst-1",
    )

    final = await _reload_assessment(real_database, assessment)
    validation_entry = final.workflow_progress.get(StageType.VALIDATION)
    assert validation_entry.status.value == "COMPLETE"
    assert validation_entry.attempt_count == 3  # failed twice, succeeded on the third
    assert final.status.value == "VALIDATED"


async def test_validation_stage_permanent_failure_blocks_workflow(real_database: Database) -> None:
    template = await _create_published_template(real_database, hazard_type=HazardType.DROUGHT)
    assessment = await _create_ready_assessment(real_database, hazard_type=HazardType.DROUGHT)

    executor = CompositeStageExecutor(
        default=ImmediateSuccessStageExecutor(),
        overrides={
            StageType.VALIDATION: ValidationStageExecutor(
                real_database, resolver=_AlwaysErrorsResolver()
            )
        },
    )
    engine = WorkflowEngine(real_database, executor)
    await engine.start_workflow(
        tenant_id=str(assessment.tenant_id),
        assessment_id=str(assessment.id),
        workflow_template_id=str(template.id),
        actor="analyst-1",
    )

    final = await _reload_assessment(real_database, assessment)
    validation_entry = final.workflow_progress.get(StageType.VALIDATION)
    assert validation_entry.status.value == "FAILED"
    assert (
        final.status.value == "RUNNING"
    )  # never advances — matches Sprint 3's blocked-workflow behavior
