"""The Sprint 5 success test: "the entire FIRAS workflow must execute
without changing platform code. Only a strategy registration should be
required." This test builds a real 6-stage FIRAS workflow template
(Hazard || Exposure || Vulnerability -> Risk || Resilience -> Validation —
exercising both parallel fan-out and multi-predecessor convergence), wires
``FIRASHazardStrategy`` into a ``StrategyRegistry`` and composes the exact
same ``CompositeStageExecutor`` shape ``api/app.py`` uses, then drives it
through Sprint 3's unmodified ``WorkflowEngine`` end to end against a real
Postgres instance — proving the composition-root extension point built in
Sprint 3/4 is genuinely sufficient for a real hazard strategy, not just a
stub.

Uses the ``real_database`` fixture (a genuine, independently-connecting
``Database``) — the same reasoning as every prior sprint's workflow-engine
integration tests: ``WorkflowEngine``, ``AnalysisStageExecutor``, and
``ValidationStageExecutor`` each open their own sequential transactions.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from georisk.api.workflow_stage_executors import (
    AnalysisStageExecutor,
    CompositeStageExecutor,
    ValidationStageExecutor,
)
from georisk.contexts.analysis.application.strategy_registry import StrategyRegistry
from georisk.contexts.analysis.domain.value_objects import HazardType as AnalysisHazardType
from georisk.contexts.analysis.infrastructure.models import StageResultModel
from georisk.contexts.analysis.strategies.firas.strategy import FIRASHazardStrategy
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
from georisk.contexts.validation.infrastructure.models import ValidationRunModel
from georisk.db.session import Database

pytestmark = pytest.mark.integration


def _firas_stage_definitions() -> tuple[StageDefinition, ...]:
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
            stage_type=StageType.RESILIENCE,
            required_predecessors=frozenset({StageType.VULNERABILITY}),
        ),
        StageDefinition(
            stage_type=StageType.VALIDATION,
            required_predecessors=frozenset({StageType.RISK, StageType.RESILIENCE}),
        ),
    )


def _build_composite_executor(db: Database) -> CompositeStageExecutor:
    """Mirrors ``api/app.py``'s lifespan wiring exactly — the only
    difference from production wiring is constructing it directly in a
    test instead of inside a FastAPI lifespan.
    """
    registry = StrategyRegistry()
    registry.register(AnalysisHazardType.FLOOD, FIRASHazardStrategy())
    analysis_executor = AnalysisStageExecutor(db, registry)
    return CompositeStageExecutor(
        default=ImmediateSuccessStageExecutor(),
        overrides={
            StageType.HAZARD: analysis_executor,
            StageType.EXPOSURE: analysis_executor,
            StageType.VULNERABILITY: analysis_executor,
            StageType.RISK: analysis_executor,
            StageType.RESILIENCE: analysis_executor,
            StageType.VALIDATION: ValidationStageExecutor(db),
        },
    )


async def _create_published_template(db: Database) -> WorkflowTemplate:
    async with db.session() as session:
        template, _ = WorkflowTemplate.create(
            hazard_type=HazardType.FLOOD,
            name=f"FIRAS Template {uuid.uuid4().hex[:8]}",
            stage_definitions=_firas_stage_definitions(),
        )
        template.publish()
        await SqlAlchemyWorkflowTemplateRepository(session).save(template)
        await session.commit()
    return template


async def _create_ready_assessment(db: Database) -> Assessment:
    tenant_id = TenantId.new()
    async with db.session() as session:
        assessment, _ = Assessment.create(
            tenant_id=tenant_id,
            name=f"FIRAS Assessment {uuid.uuid4().hex[:8]}",
            hazard_type=HazardType.FLOOD,
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


async def test_entire_firas_workflow_executes_via_strategy_registration_alone(
    real_database: Database,
) -> None:
    template = await _create_published_template(real_database)
    assessment = await _create_ready_assessment(real_database)
    executor = _build_composite_executor(real_database)

    engine = WorkflowEngine(real_database, executor)
    await engine.start_workflow(
        tenant_id=str(assessment.tenant_id),
        assessment_id=str(assessment.id),
        workflow_template_id=str(template.id),
        actor="analyst-1",
    )

    final = await _reload_assessment(real_database, assessment)
    assert final.status.value == "VALIDATED"
    for stage_type in (
        StageType.HAZARD,
        StageType.EXPOSURE,
        StageType.VULNERABILITY,
        StageType.RISK,
        StageType.RESILIENCE,
        StageType.VALIDATION,
    ):
        entry = final.workflow_progress.get(stage_type)
        assert entry.status.value == "COMPLETE", f"{stage_type} did not complete"

    async with real_database.session() as session:
        result = await session.execute(
            select(StageResultModel).where(
                StageResultModel.assessment_id == uuid.UUID(str(final.id))
            )
        )
        stage_results = {m.stage_type: m for m in result.scalars().all()}

    assert set(stage_results.keys()) == {
        "HAZARD",
        "EXPOSURE",
        "VULNERABILITY",
        "RISK",
        "RESILIENCE",
    }
    for model in stage_results.values():
        assert model.status == "COMPLETE"
        assert model.hazard_type == "FLOOD"

    hazard_indicators = {i["code"]: i["value"] for i in stage_results["HAZARD"].indicators}
    assert hazard_indicators["flood_hazard_index"] == pytest.approx(0.565)

    exposure_indicators = {i["code"]: i["value"] for i in stage_results["EXPOSURE"].indicators}
    assert exposure_indicators["flood_exposure_index"] == pytest.approx(0.4067)

    vulnerability_indicators = {
        i["code"]: i["value"] for i in stage_results["VULNERABILITY"].indicators
    }
    assert vulnerability_indicators["flood_vulnerability_index"] == pytest.approx(0.4875)
    assert vulnerability_indicators["flood_insecurity_index"] == pytest.approx(0.4792, abs=1e-4)

    risk_indicators = {i["code"]: i["value"] for i in stage_results["RISK"].indicators}
    assert risk_indicators["flood_risk_index"] == pytest.approx(0.1101, abs=1e-4)

    resilience_indicators = {i["code"]: i["value"] for i in stage_results["RESILIENCE"].indicators}
    assert resilience_indicators["community_resilience_index"] == pytest.approx(0.5225, abs=1e-4)

    for model in stage_results.values():
        assert model.strategy_version == "firas-2.0"
        assert model.formula_version is not None

    # Validation really ran too, as its own independent aggregate/outbox
    # trail (Sprint 4's integration, entirely untouched by this sprint).
    async with real_database.session() as session:
        validation_result = await session.execute(
            select(ValidationRunModel).where(
                ValidationRunModel.assessment_id == uuid.UUID(str(final.id))
            )
        )
        validation_runs = validation_result.scalars().all()
    assert len(validation_runs) == 1


async def test_resilience_completes_even_when_risk_would_be_blocked(
    real_database: Database,
) -> None:
    """Structural proof that Resilience's dependency really is Vulnerability
    alone: a template with Resilience but no Risk-supporting Exposure stage
    still lets Resilience complete once Vulnerability does.
    """
    stage_definitions = (
        StageDefinition(stage_type=StageType.VULNERABILITY),
        StageDefinition(
            stage_type=StageType.RESILIENCE,
            required_predecessors=frozenset({StageType.VULNERABILITY}),
        ),
    )
    async with real_database.session() as session:
        template, _ = WorkflowTemplate.create(
            hazard_type=HazardType.FLOOD,
            name=f"Resilience Only {uuid.uuid4().hex[:8]}",
            stage_definitions=stage_definitions,
        )
        template.publish()
        await SqlAlchemyWorkflowTemplateRepository(session).save(template)
        await session.commit()

    assessment = await _create_ready_assessment(real_database)
    executor = _build_composite_executor(real_database)
    engine = WorkflowEngine(real_database, executor)
    await engine.start_workflow(
        tenant_id=str(assessment.tenant_id),
        assessment_id=str(assessment.id),
        workflow_template_id=str(template.id),
        actor="analyst-1",
    )

    final = await _reload_assessment(real_database, assessment)
    assert final.status.value == "VALIDATED"
    assert final.workflow_progress.get(StageType.RESILIENCE).status.value == "COMPLETE"
