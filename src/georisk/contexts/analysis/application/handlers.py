"""``RecordStageResultCommand`` handler — one transaction, one aggregate
(``StageResult``), per Application Layer §9. Gathers whatever inputs the
target stage needs (raw stub inputs for leaf stages, via
``IndicatorInputProvider``; prior ``StageResult`` indicator values for
derived stages, read via the repository — "not live join," Application
Layer §12), assembles the frozen ``ComputationSnapshot``, resolves the
calculator via the injected ``StrategyRegistry``, computes, persists, and
appends both resulting events to the outbox. Never imports anything from
``contexts.assessment`` or ``contexts.validation`` — the "Do not modify
Assessment/Workflow Engine/Validation" instruction's structural
counterpart, identical reasoning to Sprint 4's ``RunValidationHandler``.

Sprint 6 (WRRAS onboarding) generified ``_gather_inputs``: it used to
hardcode FIRAS's exact indicator codes for Risk/Resilience directly here
(``flood_hazard_index``, ``flood_insecurity_index``, ...) — an
architecture defect invisible with only one hazard type registered.
Which prior stages feed which stage, and under which indicator codes, is
now a declaration on the resolved ``HazardStrategy``
(``input_dependencies``/``historical_stages`` — see
``domain/strategy.py``), so this handler needs no hazard-type-specific
branching at all, for FIRAS, WRRAS, or any future registrant.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.analysis.application.commands import RecordStageResultCommand
from georisk.contexts.analysis.application.ports import IndicatorInputProvider
from georisk.contexts.analysis.application.strategy_registry import StrategyRegistry
from georisk.contexts.analysis.domain.entities import StageResult
from georisk.contexts.analysis.domain.errors import InvalidIndicatorInputError
from georisk.contexts.analysis.domain.events import StageResultComputed, StageResultFailed
from georisk.contexts.analysis.domain.strategy import HazardStrategy, StageCalculator
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    HazardType,
    StageType,
    confidence_tier_for_sample_size,
)
from georisk.contexts.analysis.infrastructure.repositories import SqlAlchemyStageResultRepository
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.db.outbox_writer import append_event


def _join_with_and(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


class RecordStageResultHandler:
    def __init__(
        self,
        session: AsyncSession,
        registry: StrategyRegistry,
        input_provider: IndicatorInputProvider,
    ) -> None:
        self._session = session
        self._registry = registry
        self._input_provider = input_provider
        self._repo = SqlAlchemyStageResultRepository(session)

    async def handle(self, command: RecordStageResultCommand) -> StageResult:
        tenant_id = TenantId.from_string(command.tenant_id)
        hazard_type = HazardType(command.hazard_type)
        stage_type = StageType(command.stage_type)

        outcome_event: StageResultComputed | StageResultFailed
        strategy: HazardStrategy | None = None
        calculator: StageCalculator | None = None
        try:
            # Resolved first, before gathering inputs: a resolution
            # failure (unregistered hazard type, unsupported stage) and an
            # input-gathering failure (missing prior stage) are both
            # quarantined into the same FAILED path below, but resolving
            # first means an input-gathering failure still records which
            # calculator *would* have run.
            strategy = self._registry.get_strategy(hazard_type)
            calculator = self._registry.resolve(hazard_type, stage_type)

            raw_inputs = await self._gather_inputs(
                tenant_id, hazard_type, command.assessment_id, strategy, stage_type
            )
            historical: list[dict] = []
            if stage_type in strategy.historical_stages():
                historical = await self._repo.list_historical_indicators(
                    tenant_id,
                    hazard_type,
                    stage_type,
                    exclude_assessment_id=command.assessment_id,
                )
            compute_snapshot = ComputationSnapshot(inputs=raw_inputs, historical=tuple(historical))
            indicators = calculator.compute(compute_snapshot)
            confidence = confidence_tier_for_sample_size(len(historical) + 1)
            version = await self._repo.next_version(tenant_id, command.assessment_id, stage_type)

            # Persisted snapshot enriches the raw inputs with this round's
            # computed indicator values (e.g. Vulnerability's five FII
            # sub-scores and FVI) — future historical lookups for this
            # same (tenant, hazard_type, stage_type) need those computed
            # values, not just the raw inputs, per Vulnerability's own EWM
            # steps. ``historical`` itself is deliberately NOT persisted
            # (see ``ComputationSnapshot.historical``'s docstring) — only
            # its count, for audit.
            persisted_snapshot = ComputationSnapshot(
                inputs={**raw_inputs, **indicators.as_dict()}, historical_count=len(historical)
            )

            result, outcome_event = StageResult.complete(
                tenant_id=tenant_id,
                assessment_id=command.assessment_id,
                hazard_type=hazard_type,
                stage_type=stage_type,
                version=version,
                indicators=indicators,
                confidence_tier=confidence,
                snapshot=persisted_snapshot,
                issued_by=command.issued_by,
                strategy_version=strategy.strategy_version,
                formula_version=calculator.formula_version,
            )
        except Exception as exc:  # noqa: BLE001 — quarantining a calculator's
            # validation failure (bad indicator range, missing prior-stage
            # dependency) into a domain fact (StageResult.FAILED +
            # StageResultFailed), the same "isolate an untrusted boundary"
            # reasoning as Sprint 4's RunValidationHandler.
            version = await self._repo.next_version(tenant_id, command.assessment_id, stage_type)
            result, outcome_event = StageResult.failed(
                tenant_id=tenant_id,
                assessment_id=command.assessment_id,
                hazard_type=hazard_type,
                stage_type=stage_type,
                version=version,
                snapshot=ComputationSnapshot(inputs={}),
                error=str(exc),
                issued_by=command.issued_by,
                strategy_version=strategy.strategy_version if strategy is not None else None,
                formula_version=calculator.formula_version if calculator is not None else None,
            )

        await self._repo.save(result)
        await append_event(
            self._session,
            aggregate_type="StageResult",
            aggregate_id=str(result.id),
            event_type=outcome_event.event_type,
            payload=outcome_event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return result

    async def _gather_inputs(
        self,
        tenant_id: TenantId,
        hazard_type: HazardType,
        assessment_id: str,
        strategy: HazardStrategy,
        stage_type: StageType,
    ) -> dict:
        dependencies = strategy.input_dependencies(stage_type)
        if not dependencies:
            return await self._input_provider.provide_raw_inputs(
                hazard_type=hazard_type, stage_type=stage_type, assessment_id=assessment_id
            )

        inputs: dict = {}
        missing: list[StageType] = []
        for dep_stage_type, indicator_map in dependencies.items():
            dep_result = await self._repo.get_latest(tenant_id, assessment_id, dep_stage_type)
            if dep_result is None or dep_result.indicators is None:
                missing.append(dep_stage_type)
                continue
            for source_code, target_key in indicator_map.items():
                inputs[target_key] = dep_result.indicators.value(source_code)

        if missing:
            labels = [dep.value.title() for dep in dependencies if dep in missing]
            raise InvalidIndicatorInputError(
                f"{stage_type.value.title()} requires completed {_join_with_and(labels)} results"
            )
        return inputs
