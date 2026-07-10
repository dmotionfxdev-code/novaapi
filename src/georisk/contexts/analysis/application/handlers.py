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

from georisk.contexts.analysis.application.commands import (
    GenerateRiskLayerCommand,
    RecordStageResultCommand,
)
from georisk.contexts.analysis.application.ports import IndicatorInputProvider
from georisk.contexts.analysis.application.strategy_registry import StrategyRegistry
from georisk.contexts.analysis.domain.entities import RiskLayer, StageResult
from georisk.contexts.analysis.domain.errors import (
    InvalidIndicatorInputError,
    RiskLayerGenerationError,
    StageResultNotFoundError,
)
from georisk.contexts.analysis.domain.events import StageResultComputed, StageResultFailed
from georisk.contexts.analysis.domain.strategy import HazardStrategy, StageCalculator
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    HazardType,
    StageResultId,
    StageResultStatus,
    StageType,
    confidence_tier_for_sample_size,
)
from georisk.contexts.analysis.infrastructure.repositories import (
    SqlAlchemyRiskLayerRepository,
    SqlAlchemyStageResultRepository,
)
from georisk.contexts.analysis.infrastructure.risk_layer_generator import build_risk_layer
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


class GenerateRiskLayerHandler:
    """Sprint C — one transaction, one aggregate (``RiskLayer``), same
    shape as ``RecordStageResultHandler`` above. Never imports
    ``contexts.data_acquisition`` — ``command.features``/``geometry_type``/
    ``crs`` arrive already resolved (the composition root,
    ``api/risk_layer_ports.py``, is the only code allowed to read Data
    Acquisition's real Shapefile-sourced geometries). This handler's own
    job is narrow: load the target ``StageResult``, hand its real
    computed values to the business-formula-free
    ``risk_layer_generator``, persist the result.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._stage_result_repo = SqlAlchemyStageResultRepository(session)
        self._risk_layer_repo = SqlAlchemyRiskLayerRepository(session)

    async def handle(self, command: GenerateRiskLayerCommand) -> RiskLayer:
        tenant_id = TenantId.from_string(command.tenant_id)
        stage_result = await self._stage_result_repo.get_by_id(
            StageResultId.from_string(command.stage_result_id)
        )
        if stage_result is None or stage_result.tenant_id != tenant_id:
            raise StageResultNotFoundError(f"StageResult {command.stage_result_id} not found")
        if stage_result.stage_type is not StageType.RISK:
            raise RiskLayerGenerationError(
                f"Risk layers are only generated from the RISK stage, not "
                f"{stage_result.stage_type.value}"
            )
        if stage_result.status is not StageResultStatus.COMPLETE or stage_result.indicators is None:
            raise RiskLayerGenerationError(
                f"StageResult {command.stage_result_id} is not a COMPLETE result with indicators"
            )
        if not stage_result.indicators.indicators:
            raise RiskLayerGenerationError(
                f"StageResult {command.stage_result_id} has no indicators to derive a risk "
                f"index from"
            )
        if stage_result.formula_version is None:
            raise RiskLayerGenerationError(
                f"StageResult {command.stage_result_id} has no recorded formula_version"
            )

        # The RISK stage's own calculator always produces exactly one
        # risk-index indicator (confirmed against both FIRAS's and
        # WRRAS's risk.py) — read generically, by position, never by a
        # hardcoded hazard-specific code name (e.g. "flood_risk_index"),
        # so this handler never needs to know which hazard strategy ran.
        risk_index = stage_result.indicators.indicators[0].value
        hazard_specific_attributes = stage_result.indicators.as_dict()

        version = await self._risk_layer_repo.next_version(
            tenant_id, command.assessment_id, stage_result.stage_type
        )
        built = build_risk_layer(
            features=command.features,
            assessment_id=command.assessment_id,
            hazard_type=stage_result.hazard_type.value,
            stage_type=stage_result.stage_type.value,
            dataset_id=command.dataset_id,
            geometry_type=command.geometry_type,
            risk_index=risk_index,
            analysis_timestamp=stage_result.created_at,
            formula_version=stage_result.formula_version,
            hazard_specific_attributes=hazard_specific_attributes,
        )

        layer, event = RiskLayer.generate(
            tenant_id=tenant_id,
            assessment_id=command.assessment_id,
            hazard_type=stage_result.hazard_type,
            stage_type=stage_result.stage_type,
            stage_result_id=stage_result.id,
            dataset_id=command.dataset_id,
            version=version,
            geometry_type=built.geometry_type,
            feature_count=built.feature_count,
            bounding_box=built.bounding_box,
            crs=command.crs,
            risk_index=built.risk_index,
            risk_level=built.risk_level,
            classification=built.classification,
            formula_version=stage_result.formula_version,
            geojson=built.geojson,
        )
        await self._risk_layer_repo.save(layer)
        await append_event(
            self._session,
            aggregate_type="RiskLayer",
            aggregate_id=str(layer.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return layer
