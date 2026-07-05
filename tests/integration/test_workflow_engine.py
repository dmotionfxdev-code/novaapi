"""``WorkflowEngine`` integration tests against a real Postgres instance —
the core proof this sprint exists to deliver: parallel fan-out (requirement
#7), strict sequential dependency waiting (#8), manual vs. automatic
triggers (#9/#10), and the retry mechanism (#11), all driven through the
actual command-handler pipeline, not mocked.

Uses the ``real_database`` fixture (a genuine, independently-connecting
``Database``) rather than ``db_session``'s single-transaction-with-rollback
fixture, because ``WorkflowEngine`` deliberately opens several of its own
sequential transactions per call — the whole point being proven here is
that each step really does commit independently (Application Layer §9's
one-transaction-per-command rule), which a savepoint-scoped session would
mask. Tests therefore generate unique names per run rather than relying on
rollback isolation, the same accepted tradeoff already documented in
``tests/integration/conftest.py`` for ``RegisterTenantHandler``.
"""

from __future__ import annotations

import uuid

import pytest

from georisk.contexts.assessment.application.workflow_engine import (
    StageExecutionOutcome,
    WorkflowEngine,
)
from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.value_objects import HazardType
from georisk.contexts.assessment.domain.workflow_template import WorkflowTemplate
from georisk.contexts.assessment.domain.workflow_value_objects import (
    StageDefinition,
    StageExecutionStatus,
    StageType,
    TriggerMode,
)
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.assessment.infrastructure.workflow_repositories import (
    SqlAlchemyWorkflowTemplateRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.db.session import Database

pytestmark = pytest.mark.integration


class _FlakyStageExecutor:
    """Fails ``fail_stage_type`` the first ``fail_times`` times it's asked
    to execute it, then succeeds — exercises the retry mechanism without
    depending on anything real (Roadmap's stub-first posture).
    """

    def __init__(self, fail_stage_type: StageType, fail_times: int) -> None:
        self._fail_stage_type = fail_stage_type
        self._fail_times = fail_times
        self._attempts = 0

    async def execute(self, stage_type: StageType, *, assessment_id: str) -> StageExecutionOutcome:
        if stage_type == self._fail_stage_type and self._attempts < self._fail_times:
            self._attempts += 1
            return StageExecutionOutcome(success=False, error="simulated transient failure")
        return StageExecutionOutcome(
            success=True, stage_result_ref=f"stub:{assessment_id}:{stage_type.value}"
        )


class _AlwaysFailingStageExecutor:
    async def execute(self, stage_type: StageType, *, assessment_id: str) -> StageExecutionOutcome:
        return StageExecutionOutcome(success=False, error="permanent failure")


class _AlwaysSuccessExecutor:
    async def execute(self, stage_type: StageType, *, assessment_id: str) -> StageExecutionOutcome:
        return StageExecutionOutcome(
            success=True, stage_result_ref=f"stub:{assessment_id}:{stage_type.value}"
        )


async def _create_published_template(
    db: Database, *, hazard_type: HazardType, stage_definitions: tuple[StageDefinition, ...]
) -> WorkflowTemplate:
    async with db.session() as session:
        template, _ = WorkflowTemplate.create(
            hazard_type=hazard_type,
            name=f"Test Template {uuid.uuid4().hex[:8]}",
            stage_definitions=stage_definitions,
        )
        template.publish()
        repo = SqlAlchemyWorkflowTemplateRepository(session)
        await repo.save(template)
        await session.commit()
    return template


async def _create_ready_assessment(db: Database, *, hazard_type: HazardType) -> Assessment:
    tenant_id = TenantId.new()
    async with db.session() as session:
        assessment, _ = Assessment.create(
            tenant_id=tenant_id,
            name=f"Engine Test {uuid.uuid4().hex[:8]}",
            hazard_type=hazard_type,
            created_by=UserId.new(),
        )
        assessment.mark_ready(changed_by="tester")
        repo = SqlAlchemyAssessmentRepository(session)
        await repo.save(assessment)
        await session.commit()
    return assessment


async def _reload(db: Database, assessment: Assessment) -> Assessment:
    async with db.session() as session:
        repo = SqlAlchemyAssessmentRepository(session)
        reloaded = await repo.get_by_id(assessment.id)
        assert reloaded is not None
        return reloaded


def _parallel_then_sequential() -> tuple[StageDefinition, ...]:
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


def _strictly_sequential() -> tuple[StageDefinition, ...]:
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


async def test_parallel_flow_runs_to_completion_and_advances_assessment(
    real_database: Database,
) -> None:
    template = await _create_published_template(
        real_database, hazard_type=HazardType.FLOOD, stage_definitions=_parallel_then_sequential()
    )
    assessment = await _create_ready_assessment(real_database, hazard_type=HazardType.FLOOD)

    engine = WorkflowEngine(real_database, _AlwaysSuccessExecutor())
    await engine.start_workflow(
        tenant_id=str(assessment.tenant_id),
        assessment_id=str(assessment.id),
        workflow_template_id=str(template.id),
        actor="analyst-1",
    )

    final = await _reload(real_database, assessment)
    assert final.status.value == "VALIDATED"
    for stage_type in (
        StageType.HAZARD,
        StageType.EXPOSURE,
        StageType.VULNERABILITY,
        StageType.RISK,
        StageType.VALIDATION,
    ):
        assert final.workflow_progress.get(stage_type).status == StageExecutionStatus.COMPLETE


async def test_sequential_flow_completes_stages_in_dependency_order(
    real_database: Database,
) -> None:
    template = await _create_published_template(
        real_database, hazard_type=HazardType.WILDFIRE, stage_definitions=_strictly_sequential()
    )
    assessment = await _create_ready_assessment(real_database, hazard_type=HazardType.WILDFIRE)

    engine = WorkflowEngine(real_database, _AlwaysSuccessExecutor())
    await engine.start_workflow(
        tenant_id=str(assessment.tenant_id),
        assessment_id=str(assessment.id),
        workflow_template_id=str(template.id),
        actor="analyst-1",
    )

    final = await _reload(real_database, assessment)
    assert final.status.value == "VALIDATED"
    for stage_type in (
        StageType.HAZARD,
        StageType.EXPOSURE,
        StageType.VULNERABILITY,
        StageType.RISK,
    ):
        assert final.workflow_progress.get(stage_type).status == StageExecutionStatus.COMPLETE


async def test_manual_stage_stays_not_started_until_explicitly_triggered(
    real_database: Database,
) -> None:
    stage_definitions = (
        StageDefinition(stage_type=StageType.HAZARD),
        StageDefinition(
            stage_type=StageType.RISK,
            required_predecessors=frozenset({StageType.HAZARD}),
            trigger_mode=TriggerMode.MANUAL,
        ),
    )
    template = await _create_published_template(
        real_database, hazard_type=HazardType.DROUGHT, stage_definitions=stage_definitions
    )
    assessment = await _create_ready_assessment(real_database, hazard_type=HazardType.DROUGHT)

    engine = WorkflowEngine(real_database, _AlwaysSuccessExecutor())
    await engine.start_workflow(
        tenant_id=str(assessment.tenant_id),
        assessment_id=str(assessment.id),
        workflow_template_id=str(template.id),
        actor="analyst-1",
    )

    mid = await _reload(real_database, assessment)
    assert mid.status.value == "RUNNING"  # blocked — Risk never auto-dispatched
    assert mid.workflow_progress.get(StageType.HAZARD).status == StageExecutionStatus.COMPLETE
    assert mid.workflow_progress.get(StageType.RISK).status == StageExecutionStatus.NOT_STARTED

    # A user now manually triggers the MANUAL stage.
    await engine.execute_stage(
        tenant_id=str(assessment.tenant_id),
        assessment_id=str(assessment.id),
        stage_type=StageType.RISK,
        actor="analyst-1",
    )

    final = await _reload(real_database, assessment)
    assert final.status.value == "VALIDATED"
    assert final.workflow_progress.get(StageType.RISK).status == StageExecutionStatus.COMPLETE


async def test_retry_mechanism_recovers_from_transient_failure(real_database: Database) -> None:
    template = await _create_published_template(
        real_database,
        hazard_type=HazardType.LANDSLIDE,
        stage_definitions=(StageDefinition(stage_type=StageType.HAZARD, max_attempts=3),),
    )
    assessment = await _create_ready_assessment(real_database, hazard_type=HazardType.LANDSLIDE)

    executor = _FlakyStageExecutor(fail_stage_type=StageType.HAZARD, fail_times=2)
    engine = WorkflowEngine(real_database, executor)
    await engine.start_workflow(
        tenant_id=str(assessment.tenant_id),
        assessment_id=str(assessment.id),
        workflow_template_id=str(template.id),
        actor="analyst-1",
    )

    final = await _reload(real_database, assessment)
    entry = final.workflow_progress.get(StageType.HAZARD)
    assert entry.status == StageExecutionStatus.COMPLETE
    assert entry.attempt_count == 3  # failed twice, succeeded on the third
    assert final.status.value == "VALIDATED"


async def test_retry_mechanism_gives_up_after_max_attempts_and_blocks_workflow(
    real_database: Database,
) -> None:
    template = await _create_published_template(
        real_database,
        hazard_type=HazardType.LANDSLIDE,
        stage_definitions=(StageDefinition(stage_type=StageType.HAZARD, max_attempts=2),),
    )
    assessment = await _create_ready_assessment(real_database, hazard_type=HazardType.LANDSLIDE)

    engine = WorkflowEngine(real_database, _AlwaysFailingStageExecutor())
    await engine.start_workflow(
        tenant_id=str(assessment.tenant_id),
        assessment_id=str(assessment.id),
        workflow_template_id=str(template.id),
        actor="analyst-1",
    )

    final = await _reload(real_database, assessment)
    entry = final.workflow_progress.get(StageType.HAZARD)
    assert entry.status == StageExecutionStatus.FAILED
    assert entry.attempt_count == 2
    assert final.status.value == "RUNNING"  # never advances — workflow blocked
