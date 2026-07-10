"""Composition-root glue wiring the Validation and Analysis contexts into
Assessment's Workflow Engine as stages (Sprint 4: "Validation must
integrate with Workflow Engine as a stage"; Sprint 5: the same requirement
for the FIRAS hazard strategy). Lives here, under ``api/``, deliberately
outside ``contexts.assessment``, ``contexts.validation``, and
``contexts.analysis`` — the import-linter's peer-independence contract
forbids any of these bounded contexts from importing another, so the only
place code needing BOTH Assessment's ``WorkflowEngine.StageExecutor``
protocol AND another context's own command handler can legally live is a
neutral composition layer, the same role ``api/app.py`` already plays
wiring routers from multiple contexts together. None of these contexts
imports this module — it's wired in only where
``contexts/assessment/interface/routes.py`` constructs a ``WorkflowEngine``.
"""

from __future__ import annotations

import contextlib

from georisk.contexts.analysis.application.commands import RecordStageResultCommand
from georisk.contexts.analysis.application.handlers import RecordStageResultHandler
from georisk.contexts.analysis.application.ports import (
    IndicatorInputProvider,
    RiskLayerGenerationPort,
    StubIndicatorInputProvider,
)
from georisk.contexts.analysis.application.strategy_registry import StrategyRegistry
from georisk.contexts.analysis.domain.value_objects import (
    StageResultStatus as AnalysisStageResultStatus,
)
from georisk.contexts.analysis.domain.value_objects import (
    StageType as AnalysisStageType,
)
from georisk.contexts.assessment.application.workflow_engine import (
    StageExecutionOutcome,
    StageExecutor,
)
from georisk.contexts.assessment.domain.value_objects import AssessmentId
from georisk.contexts.assessment.domain.workflow_value_objects import StageType
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.validation.application.commands import RunValidationCommand
from georisk.contexts.validation.application.handlers import RunValidationHandler
from georisk.contexts.validation.application.ports import (
    StubValidationSubjectResolver,
    ValidationSubjectResolver,
)
from georisk.contexts.validation.domain.value_objects import SubjectType, ValidationRunStatus
from georisk.db.session import Database


class CompositeStageExecutor:
    """Routes a stage's execution to a per-``StageType`` override if one is
    registered, else a default executor. Requires no change to
    ``WorkflowEngine`` itself (Sprint 3) — it's just another
    ``StageExecutor`` implementation composed of others, injected the
    identical way Sprint 3's single stub was.
    """

    def __init__(
        self, *, default: StageExecutor, overrides: dict[StageType, StageExecutor]
    ) -> None:
        self._default = default
        self._overrides = overrides

    async def execute(self, stage_type: StageType, *, assessment_id: str) -> StageExecutionOutcome:
        executor = self._overrides.get(stage_type, self._default)
        return await executor.execute(stage_type, assessment_id=assessment_id)


class ValidationStageExecutor:
    """Implements Assessment's ``StageExecutor`` protocol using Validation's
    ``RunValidationCommand`` pipeline for ``StageType.VALIDATION``. Reads
    Assessment's ``WorkflowProgress`` read-only (via the same repository the
    Workflow Engine itself already uses) to find the RISK stage's
    ``stage_result_ref`` as the subject to validate — a read, not a
    mutation: this class calls exactly one Assessment repository
    ``get_by_id`` and zero Assessment commands. The *only* thing that ever
    changes Assessment state afterwards is the pre-existing
    ``WorkflowEngine`` (``RecordStageCompletionCommand``/
    ``RecordStageFailureCommand``), reacting to the ``StageExecutionOutcome``
    this class returns exactly like it reacts to every other stage's
    outcome — "Validation never mutates Assessment directly" holds
    structurally, not by convention.

    ``StageExecutionOutcome.success`` reflects whether the *validation run
    itself completed* (a computation succeeding), never the run's
    PASS/FAIL *verdict*: a FAIL verdict is a legitimate, complete answer
    ("this subject didn't meet the bar"), not an execution error, and must
    not trigger the Workflow Engine's retry mechanism the way a genuine
    computation failure should. ``RunValidationHandler`` never raises for
    an expected resolver/computation error — it converts that into a
    ``ValidationRun`` whose ``status`` is ``FAILED`` (``ValidationRunStatus
    .FAILED``, distinct from ``Verdict.FAIL``) and returns it normally.
    This class checks exactly that: ``run.status is ValidationRunStatus
    .FAILED`` maps to ``success=False`` (triggering retry); a completed
    run — PASS or FAIL verdict alike — maps to ``success=True``. The
    ``try/except`` around the handler call only catches what gets past
    the handler's own boundary entirely (e.g. a database error opening
    the session).
    """

    def __init__(self, db: Database, resolver: ValidationSubjectResolver | None = None) -> None:
        self._db = db
        self._resolver = resolver if resolver is not None else StubValidationSubjectResolver()

    async def execute(self, stage_type: StageType, *, assessment_id: str) -> StageExecutionOutcome:
        async with self._db.session() as session:
            assessment_repo = SqlAlchemyAssessmentRepository(session)
            assessment = await assessment_repo.get_by_id(AssessmentId.from_string(assessment_id))
            if assessment is None:
                return StageExecutionOutcome(
                    success=False, error=f"Assessment {assessment_id} not found"
                )
            tenant_id = str(assessment.tenant_id)
            risk_entry = assessment.workflow_progress.get(StageType.RISK)
            # Falls back to a stable synthetic reference for templates that
            # validate without a preceding Risk stage, rather than failing
            # the whole stage outright.
            subject_id = risk_entry.stage_result_ref or f"assessment:{assessment_id}"

        async with self._db.session() as session:
            handler = RunValidationHandler(session, self._resolver)
            try:
                run = await handler.handle(
                    RunValidationCommand(
                        tenant_id=tenant_id,
                        assessment_id=assessment_id,
                        subject_id=subject_id,
                        subject_type=SubjectType.STAGE_RESULT.value,
                        issued_by="system:workflow-engine",
                    )
                )
            except Exception as exc:  # noqa: BLE001 — an even-more-unexpected
                # failure that gets past RunValidationHandler's own
                # try/except entirely (e.g. a database error opening the
                # session) — belt-and-braces alongside the ``run.status``
                # check below, which is what normally carries this signal.
                return StageExecutionOutcome(success=False, error=str(exc))

        if run.status is ValidationRunStatus.FAILED:
            # A genuine execution failure (resolver/computation error) —
            # ``run.error`` is populated, ``run.verdict`` is None. This,
            # not a Verdict.FAIL, is what should trigger the Workflow
            # Engine's stage-retry mechanism (Sprint 3): the subject
            # legitimately failing its quality bar is a complete, correct
            # answer, not something retrying will fix.
            return StageExecutionOutcome(success=False, error=run.error)

        return StageExecutionOutcome(success=True, stage_result_ref=str(run.id))


class AnalysisStageExecutor:
    """Implements Assessment's ``StageExecutor`` protocol using the
    Analysis Engine's ``RecordStageResultCommand`` pipeline — Sprint 5's
    entire platform-facing integration point for FIRAS (or any future
    hazard strategy). Reads Assessment's ``hazard_type`` read-only (one
    repository ``get_by_id`` call, zero Assessment commands) so the
    injected ``StrategyRegistry`` can resolve the right calculator; the
    *only* thing that ever changes Assessment state afterwards is the
    pre-existing ``WorkflowEngine``, reacting to the
    ``StageExecutionOutcome`` this class returns — "Analysis never
    mutates Assessment directly" holds structurally, identical reasoning
    to ``ValidationStageExecutor`` above.

    One instance handles every hazard-strategy stage type (Hazard,
    Exposure, Vulnerability, Risk, Resilience) generically — which
    calculator actually runs is entirely a function of the assessment's
    ``hazard_type`` and the registry's registrations, never a branch in
    this class. Registering a fifth hazard type changes zero lines here.
    """

    def __init__(
        self,
        db: Database,
        registry: StrategyRegistry,
        input_provider: IndicatorInputProvider | None = None,
        risk_layer_service: RiskLayerGenerationPort | None = None,
    ) -> None:
        self._db = db
        self._registry = registry
        self._input_provider = (
            input_provider if input_provider is not None else StubIndicatorInputProvider()
        )
        # Sprint C: optional — tests/callers that don't pass one simply
        # never get a generated risk layer, no behavior change to the
        # actual Analysis computation this class exists to run.
        self._risk_layer_service = risk_layer_service

    async def execute(self, stage_type: StageType, *, assessment_id: str) -> StageExecutionOutcome:
        async with self._db.session() as session:
            assessment_repo = SqlAlchemyAssessmentRepository(session)
            assessment = await assessment_repo.get_by_id(AssessmentId.from_string(assessment_id))
            if assessment is None:
                return StageExecutionOutcome(
                    success=False, error=f"Assessment {assessment_id} not found"
                )
            tenant_id = str(assessment.tenant_id)
            hazard_type = assessment.hazard_type.value

        async with self._db.session() as session:
            handler = RecordStageResultHandler(session, self._registry, self._input_provider)
            try:
                result = await handler.handle(
                    RecordStageResultCommand(
                        tenant_id=tenant_id,
                        assessment_id=assessment_id,
                        hazard_type=hazard_type,
                        stage_type=stage_type.value,
                        issued_by="system:workflow-engine",
                    )
                )
            except Exception as exc:  # noqa: BLE001 — belt-and-braces for a
                # failure that gets past RecordStageResultHandler's own
                # try/except entirely (e.g. a database error opening the
                # session); the ``result.status`` check below is what
                # normally carries a calculator's own failure signal.
                return StageExecutionOutcome(success=False, error=str(exc))

        if result.status is AnalysisStageResultStatus.FAILED:
            return StageExecutionOutcome(success=False, error=result.error)

        # Sprint C requirement #8: automatic, no manual regeneration step.
        # Best-effort and never allowed to turn an already-successful RISK
        # computation into a failed stage — a missing/non-Shapefile
        # geometry source is an expected, benign outcome the service
        # itself already handles silently; suppressing here is
        # belt-and-braces against any OTHER unexpected failure in that path.
        is_risk_stage = stage_type.value == AnalysisStageType.RISK.value
        if self._risk_layer_service is not None and is_risk_stage:
            with contextlib.suppress(Exception):
                await self._risk_layer_service.generate_if_possible(
                    tenant_id=tenant_id,
                    assessment_id=assessment_id,
                    hazard_type=hazard_type,
                    stage_result_id=str(result.id),
                    issued_by="system:workflow-engine",
                )

        return StageExecutionOutcome(success=True, stage_result_ref=str(result.id))
