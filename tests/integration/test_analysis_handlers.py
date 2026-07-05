"""Handler-level integration tests against a real Postgres instance —
``RecordStageResultHandler``'s gather-inputs -> resolve-calculator ->
compute -> persist -> emit-events pipeline, including the downstream
(Risk/Resilience reading prior ``StageResult``s) data flow and the
failure path when a dependency is missing.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from georisk.contexts.analysis.application.commands import RecordStageResultCommand
from georisk.contexts.analysis.application.handlers import RecordStageResultHandler
from georisk.contexts.analysis.application.ports import StubIndicatorInputProvider
from georisk.contexts.analysis.application.strategy_registry import StrategyRegistry
from georisk.contexts.analysis.domain.value_objects import HazardType, StageResultStatus, StageType
from georisk.contexts.analysis.infrastructure.repositories import SqlAlchemyStageResultRepository
from georisk.contexts.analysis.strategies.firas.strategy import FIRASHazardStrategy
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.db.outbox_models import OutboxEventModel

pytestmark = pytest.mark.integration


def _registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(HazardType.FLOOD, FIRASHazardStrategy())
    return registry


async def test_record_hazard_stage_result(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RecordStageResultHandler(db_session, _registry(), StubIndicatorInputProvider())

    result = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="FLOOD",
            stage_type="HAZARD",
            issued_by="analyst-1",
        )
    )

    assert result.status == StageResultStatus.COMPLETE
    assert result.indicators.value("flood_hazard_index") == pytest.approx(0.565)
    assert result.version == 1

    outbox = await db_session.execute(
        select(OutboxEventModel).where(
            OutboxEventModel.aggregate_type == "StageResult",
            OutboxEventModel.aggregate_id == str(result.id),
        )
    )
    events = outbox.scalars().all()
    assert [e.event_type for e in events] == ["analysis.StageResultComputed"]


async def test_record_risk_stage_result_reads_prior_stages(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RecordStageResultHandler(db_session, _registry(), StubIndicatorInputProvider())

    for stage in ("HAZARD", "EXPOSURE", "VULNERABILITY"):
        await handler.handle(
            RecordStageResultCommand(
                tenant_id=str(tenant_id),
                assessment_id=assessment_id,
                hazard_type="FLOOD",
                stage_type=stage,
                issued_by="analyst-1",
            )
        )

    risk_result = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="FLOOD",
            stage_type="RISK",
            issued_by="analyst-1",
        )
    )

    assert risk_result.status == StageResultStatus.COMPLETE
    assert risk_result.indicators.value("flood_risk_index") == pytest.approx(0.1101, abs=1e-4)
    assert risk_result.strategy_version == "firas-2.0"
    assert risk_result.formula_version == "fri-multiplicative-v2"


async def test_record_resilience_stage_result_reads_vulnerability_only(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RecordStageResultHandler(db_session, _registry(), StubIndicatorInputProvider())

    await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="FLOOD",
            stage_type="VULNERABILITY",
            issued_by="analyst-1",
        )
    )

    # Deliberately skip Hazard/Exposure/Risk entirely — Resilience must not
    # need them.
    resilience_result = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="FLOOD",
            stage_type="RESILIENCE",
            issued_by="analyst-1",
        )
    )

    assert resilience_result.status == StageResultStatus.COMPLETE
    assert resilience_result.indicators.value("community_resilience_index") == pytest.approx(
        0.5225, abs=1e-4
    )


async def test_record_risk_without_prerequisites_produces_failed_result_not_an_exception(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RecordStageResultHandler(db_session, _registry(), StubIndicatorInputProvider())

    result = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="FLOOD",
            stage_type="RISK",
            issued_by="analyst-1",
        )
    )

    assert result.status == StageResultStatus.FAILED
    assert "Hazard, Exposure, and Vulnerability" in result.error
    # Resolution succeeds (FLOOD/RISK is a real registration) before
    # input-gathering fails, so the FAILED result still records which
    # calculator would have run, even though it never got to compute().
    assert result.strategy_version == "firas-2.0"
    assert result.formula_version == "fri-multiplicative-v2"

    outbox = await db_session.execute(
        select(OutboxEventModel).where(
            OutboxEventModel.aggregate_type == "StageResult",
            OutboxEventModel.aggregate_id == str(result.id),
        )
    )
    event_types = {e.event_type for e in outbox.scalars().all()}
    assert "analysis.StageResultFailed" in event_types


async def test_unregistered_hazard_type_produces_failed_result(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RecordStageResultHandler(db_session, _registry(), StubIndicatorInputProvider())

    result = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="WILDFIRE",
            stage_type="HAZARD",
            issued_by="analyst-1",
        )
    )
    assert result.status == StageResultStatus.FAILED
    # No strategy was ever found for WILDFIRE, so neither version is known.
    assert result.strategy_version is None
    assert result.formula_version is None


async def test_re_recording_the_same_stage_creates_a_new_version(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RecordStageResultHandler(db_session, _registry(), StubIndicatorInputProvider())

    first = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="FLOOD",
            stage_type="HAZARD",
            issued_by="analyst-1",
        )
    )
    second = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="FLOOD",
            stage_type="HAZARD",
            issued_by="analyst-1",
        )
    )

    assert first.id != second.id
    assert second.version == first.version + 1

    repo = SqlAlchemyStageResultRepository(db_session)
    latest = await repo.get_latest(tenant_id, assessment_id, StageType.HAZARD)
    assert latest is not None
    assert latest.id == second.id
