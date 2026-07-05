"""Handler-level integration tests against a real Postgres instance for
WRRAS — mirrors ``test_analysis_handlers.py``'s FIRAS coverage, proving
the identical ``RecordStageResultHandler`` pipeline works unmodified for
a second hazard type, including the three optional, non-gating
supporting-analysis stages.
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
from georisk.contexts.analysis.strategies.wrras.strategy import WRRASHazardStrategy
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.db.outbox_models import OutboxEventModel

pytestmark = pytest.mark.integration


def _registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(HazardType.WILDFIRE, WRRASHazardStrategy())
    return registry


async def test_record_hazard_stage_result(db_session) -> None:  # noqa: ANN001
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

    assert result.status == StageResultStatus.COMPLETE
    assert result.indicators.value("wildfire_hazard_index") == pytest.approx(0.58)
    assert result.strategy_version == "wrras-1.0"
    assert result.formula_version == "whi-weighted-linear-v1"

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
                hazard_type="WILDFIRE",
                stage_type=stage,
                issued_by="analyst-1",
            )
        )

    risk_result = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="WILDFIRE",
            stage_type="RISK",
            issued_by="analyst-1",
        )
    )

    assert risk_result.status == StageResultStatus.COMPLETE
    assert risk_result.indicators.value("wildfire_risk_index") == pytest.approx(0.0926, abs=1e-4)
    assert risk_result.formula_version == "wri-multiplicative-v1"


async def test_record_resilience_stage_result_reads_vulnerability_only(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RecordStageResultHandler(db_session, _registry(), StubIndicatorInputProvider())

    await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="WILDFIRE",
            stage_type="VULNERABILITY",
            issued_by="analyst-1",
        )
    )

    # Deliberately skip Hazard/Exposure/Risk entirely — Resilience must
    # not need them, matching FIRAS's identical structural proof.
    resilience_result = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="WILDFIRE",
            stage_type="RESILIENCE",
            issued_by="analyst-1",
        )
    )

    assert resilience_result.status == StageResultStatus.COMPLETE
    assert resilience_result.indicators.value(
        "community_wildfire_resilience_index"
    ) == pytest.approx(0.46, abs=1e-4)


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
            hazard_type="WILDFIRE",
            stage_type="RISK",
            issued_by="analyst-1",
        )
    )

    assert result.status == StageResultStatus.FAILED
    assert "Hazard, Exposure, and Vulnerability" in result.error
    assert result.strategy_version == "wrras-1.0"
    assert result.formula_version == "wri-multiplicative-v1"


async def test_optional_supporting_analysis_stages_complete_independently(
    db_session,  # noqa: ANN001
) -> None:
    """Fire Regime, Burn Occurrence Probability, and Burn Severity need no
    prior StageResult at all — they can run on a completely fresh
    assessment with nothing else recorded, and never touch Risk."""
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RecordStageResultHandler(db_session, _registry(), StubIndicatorInputProvider())

    fire_regime = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="WILDFIRE",
            stage_type="FIRE_REGIME",
            issued_by="analyst-1",
        )
    )
    burn_probability = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="WILDFIRE",
            stage_type="BURN_OCCURRENCE_PROBABILITY",
            issued_by="analyst-1",
        )
    )
    burn_severity = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="WILDFIRE",
            stage_type="BURN_SEVERITY",
            issued_by="analyst-1",
        )
    )

    assert fire_regime.status == StageResultStatus.COMPLETE
    assert fire_regime.indicators.value("fire_frequency") == pytest.approx(1.5)
    assert burn_probability.status == StageResultStatus.COMPLETE
    assert burn_probability.indicators.value("burn_occurrence_probability") == pytest.approx(
        0.9879, abs=1e-4
    )
    assert burn_severity.status == StageResultStatus.COMPLETE
    assert burn_severity.indicators.value("dnbr") == pytest.approx(0.4755, abs=1e-4)


async def test_unregistered_hazard_type_produces_failed_result(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RecordStageResultHandler(db_session, _registry(), StubIndicatorInputProvider())

    result = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="DROUGHT",
            stage_type="HAZARD",
            issued_by="analyst-1",
        )
    )
    assert result.status == StageResultStatus.FAILED
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
            hazard_type="WILDFIRE",
            stage_type="HAZARD",
            issued_by="analyst-1",
        )
    )
    second = await handler.handle(
        RecordStageResultCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type="WILDFIRE",
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
