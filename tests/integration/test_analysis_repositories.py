"""Repository-level integration tests against a real Postgres instance —
confirms the ``StageResult`` domain<->ORM mapping round-trips correctly,
``get_latest`` picks the highest COMPLETE version, and the EWM historical-
indicators lookup is correctly scoped per tenant/hazard/stage.
"""

from __future__ import annotations

import uuid

import pytest

from georisk.contexts.analysis.domain.entities import StageResult
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    ConfidenceTier,
    HazardType,
    Indicator,
    IndicatorSet,
    StageType,
)
from georisk.contexts.analysis.infrastructure.repositories import SqlAlchemyStageResultRepository
from georisk.contexts.identity.domain.value_objects import TenantId

pytestmark = pytest.mark.integration


def _complete(tenant_id, assessment_id, stage_type, version, value, hazard_type=HazardType.FLOOD):  # noqa: ANN001
    result, _event = StageResult.complete(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        hazard_type=hazard_type,
        stage_type=stage_type,
        version=version,
        indicators=IndicatorSet(indicators=(Indicator(code="index", value=value),)),
        confidence_tier=ConfidenceTier.LOW,
        snapshot=ComputationSnapshot(inputs={"raw": value}),
        issued_by="analyst-1",
        strategy_version="firas-2.0",
        formula_version="test-formula-v1",
    )
    return result


async def test_save_and_get_round_trips(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    result = _complete(tenant_id, assessment_id, StageType.HAZARD, 1, 0.565)
    repo = SqlAlchemyStageResultRepository(db_session)
    await repo.save(result)
    await db_session.flush()

    fetched = await repo.get_by_id(result.id)
    assert fetched is not None
    assert fetched.hazard_type == HazardType.FLOOD
    assert fetched.stage_type == StageType.HAZARD
    assert fetched.confidence_tier == ConfidenceTier.LOW
    assert fetched.indicators.value("index") == pytest.approx(0.565)
    assert fetched.snapshot.inputs == {"raw": 0.565}


async def test_get_latest_returns_highest_complete_version(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    repo = SqlAlchemyStageResultRepository(db_session)

    await repo.save(_complete(tenant_id, assessment_id, StageType.HAZARD, 1, 0.5))
    await repo.save(_complete(tenant_id, assessment_id, StageType.HAZARD, 2, 0.6))
    await db_session.flush()

    latest = await repo.get_latest(tenant_id, assessment_id, StageType.HAZARD)
    assert latest is not None
    assert latest.version == 2
    assert latest.indicators.value("index") == pytest.approx(0.6)


async def test_get_latest_ignores_failed_results(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    repo = SqlAlchemyStageResultRepository(db_session)

    await repo.save(_complete(tenant_id, assessment_id, StageType.HAZARD, 1, 0.5))
    failed, _event = StageResult.failed(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        hazard_type=HazardType.FLOOD,
        stage_type=StageType.HAZARD,
        version=2,
        snapshot=ComputationSnapshot(inputs={}),
        error="boom",
        issued_by="analyst-1",
    )
    await repo.save(failed)
    await db_session.flush()

    latest = await repo.get_latest(tenant_id, assessment_id, StageType.HAZARD)
    assert latest is not None
    assert latest.version == 1


async def test_next_version_increments_per_assessment_and_stage(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    repo = SqlAlchemyStageResultRepository(db_session)

    assert await repo.next_version(tenant_id, assessment_id, StageType.HAZARD) == 1
    await repo.save(_complete(tenant_id, assessment_id, StageType.HAZARD, 1, 0.5))
    await db_session.flush()
    assert await repo.next_version(tenant_id, assessment_id, StageType.HAZARD) == 2
    # A different stage type on the same assessment starts its own count.
    assert await repo.next_version(tenant_id, assessment_id, StageType.EXPOSURE) == 1


async def test_list_historical_indicators_scoped_and_excludes_current_assessment(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    other_tenant = TenantId.new()
    assessment_a = str(uuid.uuid4())
    assessment_b = str(uuid.uuid4())
    repo = SqlAlchemyStageResultRepository(db_session)

    await repo.save(_complete(tenant_id, assessment_a, StageType.VULNERABILITY, 1, 0.4))
    await repo.save(_complete(tenant_id, assessment_b, StageType.VULNERABILITY, 1, 0.5))
    await repo.save(_complete(other_tenant, assessment_b, StageType.VULNERABILITY, 1, 0.9))
    await db_session.flush()

    historical = await repo.list_historical_indicators(
        tenant_id, HazardType.FLOOD, StageType.VULNERABILITY, exclude_assessment_id=assessment_a
    )
    assert historical == [{"raw": 0.5}]


async def test_list_by_assessment_returns_all_stages(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    repo = SqlAlchemyStageResultRepository(db_session)

    await repo.save(_complete(tenant_id, assessment_id, StageType.HAZARD, 1, 0.5))
    await repo.save(_complete(tenant_id, assessment_id, StageType.EXPOSURE, 1, 0.4))
    await db_session.flush()

    results = await repo.list_by_assessment(tenant_id, assessment_id)
    assert {r.stage_type for r in results} == {StageType.HAZARD, StageType.EXPOSURE}
