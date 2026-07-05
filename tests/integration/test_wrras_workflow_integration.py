"""The Sprint 6 success test: WRRAS is the *second* independent proof that
"the entire [hazard] workflow must execute without changing platform
code — only a strategy registration should be required" (Sprint 5's
brief, restated for WRRAS by Sprint 6's). Builds a real WRRAS workflow
template (Hazard || Exposure || Vulnerability -> Risk || Resilience ->
Validation, matching the requested shape exactly), wires
``WRRASHazardStrategy`` into a ``StrategyRegistry`` and composes the
exact same ``CompositeStageExecutor`` shape ``api/app.py`` uses, then
drives it through Sprint 3's unmodified ``WorkflowEngine`` end to end
against a real Postgres instance.

The three optional supporting-analysis stages (Fire Regime, Burn
Occurrence Probability, Burn Severity) are deliberately **not** exercised
here via a ``WorkflowTemplate`` at all — see the Architecture Defect this
sprint found and did not fix: ``WorkflowTemplate.required_stage_types()``
returns every stage in ``stage_definitions`` regardless of
``TriggerMode``, and ``Assessment.advance_past_running()`` requires
``all_complete()`` against that full set. Including any of the three in a
template would block that assessment from ever reaching ``VALIDATED``
until someone manually completed them — the opposite of "non-gating."
That code lives in ``contexts.assessment.domain.workflow_template``, on
this sprint's explicit "DO NOT MODIFY" list. The only way to make these
three stages genuinely non-gating without touching the protected Workflow
Engine is to never register them in any template at all — they are
invoked directly via ``RecordStageResultCommand``, proven in
``test_wrras_handlers.py::test_optional_supporting_analysis_stages_complete_independently``,
entirely outside the WorkflowEngine's template-driven DAG.
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
from georisk.contexts.analysis.strategies.wrras.strategy import WRRASHazardStrategy
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


def _wrras_stage_definitions() -> tuple[StageDefinition, ...]:
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
    """Mirrors ``api/app.py``'s lifespan wiring exactly."""
    registry = StrategyRegistry()
    registry.register(AnalysisHazardType.WILDFIRE, WRRASHazardStrategy())
    analysis_executor = AnalysisStageExecutor(db, registry)
    return CompositeStageExecutor(
        default=ImmediateSuccessStageExecutor(),
        overrides={
            StageType.HAZARD: analysis_executor,
            StageType.EXPOSURE: analysis_executor,
            StageType.VULNERABILITY: analysis_executor,
            StageType.RISK: analysis_executor,
            StageType.RESILIENCE: analysis_executor,
            StageType.FIRE_REGIME: analysis_executor,
            StageType.BURN_OCCURRENCE_PROBABILITY: analysis_executor,
            StageType.BURN_SEVERITY: analysis_executor,
            StageType.VALIDATION: ValidationStageExecutor(db),
        },
    )


async def _create_published_template(db: Database) -> WorkflowTemplate:
    async with db.session() as session:
        template, _ = WorkflowTemplate.create(
            hazard_type=HazardType.WILDFIRE,
            name=f"WRRAS Template {uuid.uuid4().hex[:8]}",
            stage_definitions=_wrras_stage_definitions(),
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
            name=f"WRRAS Assessment {uuid.uuid4().hex[:8]}",
            hazard_type=HazardType.WILDFIRE,
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


async def test_entire_wrras_workflow_executes_via_strategy_registration_alone(
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
        assert model.hazard_type == "WILDFIRE"
        assert model.strategy_version == "wrras-1.0"

    hazard_indicators = {i["code"]: i["value"] for i in stage_results["HAZARD"].indicators}
    assert hazard_indicators["wildfire_hazard_index"] == pytest.approx(0.58)

    exposure_indicators = {i["code"]: i["value"] for i in stage_results["EXPOSURE"].indicators}
    assert exposure_indicators["wildfire_exposure_index"] == pytest.approx(0.3625)

    vulnerability_indicators = {
        i["code"]: i["value"] for i in stage_results["VULNERABILITY"].indicators
    }
    assert vulnerability_indicators["wildfire_vulnerability_index"] == pytest.approx(0.4406)
    assert vulnerability_indicators["wildfire_insecurity_index"] == pytest.approx(0.5234, abs=1e-4)

    risk_indicators = {i["code"]: i["value"] for i in stage_results["RISK"].indicators}
    assert risk_indicators["wildfire_risk_index"] == pytest.approx(0.0926, abs=1e-4)

    resilience_indicators = {i["code"]: i["value"] for i in stage_results["RESILIENCE"].indicators}
    assert resilience_indicators["community_wildfire_resilience_index"] == pytest.approx(
        0.46, abs=1e-4
    )

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


async def test_optional_supporting_analysis_stages_never_touch_the_workflow_template(
    real_database: Database,
) -> None:
    """Proves the Sprint 6 Architecture Defect finding structurally,
    rather than just asserting it: the WRRAS workflow template never
    declares Fire Regime / Burn Occurrence Probability / Burn Severity —
    they are absent from ``required_stage_types()`` entirely — yet Risk
    still computes correctly and the assessment still reaches VALIDATED.
    (``WorkflowTemplate.required_stage_types()`` treats every declared
    stage as gating for VALIDATED regardless of ``TriggerMode``, so
    including these three there at all would have blocked completion
    until someone manually finished them — the opposite of "non-gating."
    Genuinely invoking them is proven separately, entirely outside this
    template/engine path, in
    ``test_wrras_handlers.py::test_optional_supporting_analysis_stages_complete_independently``.)
    """
    template = await _create_published_template(real_database)
    assert StageType.FIRE_REGIME not in template.required_stage_types()
    assert StageType.BURN_OCCURRENCE_PROBABILITY not in template.required_stage_types()
    assert StageType.BURN_SEVERITY not in template.required_stage_types()

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

    async with real_database.session() as session:
        result = await session.execute(
            select(StageResultModel).where(
                StageResultModel.assessment_id == uuid.UUID(str(final.id)),
                StageResultModel.stage_type == "RISK",
            )
        )
        risk_model = result.scalar_one()

    risk_indicators = {i["code"]: i["value"] for i in risk_model.indicators}
    assert risk_indicators["wildfire_risk_index"] == pytest.approx(0.0926, abs=1e-4)


async def test_resilience_completes_even_when_risk_would_be_blocked(
    real_database: Database,
) -> None:
    """Structural proof that Resilience's dependency really is
    Vulnerability alone, matching FIRAS's identical precedent."""
    stage_definitions = (
        StageDefinition(stage_type=StageType.VULNERABILITY),
        StageDefinition(
            stage_type=StageType.RESILIENCE,
            required_predecessors=frozenset({StageType.VULNERABILITY}),
        ),
    )
    async with real_database.session() as session:
        template, _ = WorkflowTemplate.create(
            hazard_type=HazardType.WILDFIRE,
            name=f"WRRAS Resilience Only {uuid.uuid4().hex[:8]}",
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
