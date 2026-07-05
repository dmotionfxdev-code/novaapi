"""Repository-level integration tests against a real Postgres instance —
confirms the domain<->ORM mapping round-trips correctly, cursor pagination
and filtering work, and optimistic concurrency is enforced.
"""

from __future__ import annotations

import uuid

import pytest

from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.errors import OptimisticConcurrencyError
from georisk.contexts.assessment.domain.value_objects import AssessmentStatus, HazardType
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.identity.domain.value_objects import TenantId, UserId

pytestmark = pytest.mark.integration


async def test_save_and_get_round_trips(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment, _ = Assessment.create(
        tenant_id=tenant_id,
        name=f"Repo Test {uuid.uuid4().hex[:8]}",
        hazard_type=HazardType.DROUGHT,
        created_by=UserId.new(),
    )
    repo = SqlAlchemyAssessmentRepository(db_session)
    await repo.save(assessment)
    await db_session.flush()

    fetched = await repo.get_by_id(assessment.id)
    assert fetched is not None
    assert fetched.name == assessment.name
    assert fetched.hazard_type == HazardType.DROUGHT
    assert fetched.status == AssessmentStatus.DRAFT
    assert fetched.version == 0


async def test_optimistic_concurrency_conflict(db_session) -> None:  # noqa: ANN001
    assessment, _ = Assessment.create(
        tenant_id=TenantId.new(),
        name="Concurrency Test",
        hazard_type=HazardType.FLOOD,
        created_by=UserId.new(),
    )
    repo = SqlAlchemyAssessmentRepository(db_session)
    await repo.save(assessment)
    await db_session.flush()

    assessment.mark_ready(changed_by="tester")
    await repo.save(assessment, expected_version=0)
    await db_session.flush()

    stale = await repo.get_by_id(assessment.id)
    assert stale is not None
    stale.cancel(reason="stale attempt", cancelled_by="tester")
    with pytest.raises(OptimisticConcurrencyError):
        await repo.save(stale, expected_version=0)  # already advanced to version 1 above


async def test_list_by_tenant_with_status_filter_and_pagination(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    repo = SqlAlchemyAssessmentRepository(db_session)

    created = []
    for i in range(5):
        assessment, _ = Assessment.create(
            tenant_id=tenant_id,
            name=f"Paginated {i}",
            hazard_type=HazardType.FLOOD,
            created_by=UserId.new(),
        )
        await repo.save(assessment)
        created.append(assessment)
    await db_session.flush()

    # Mark two as READY, leave the rest DRAFT.
    created[0].mark_ready(changed_by="tester")
    created[1].mark_ready(changed_by="tester")
    await repo.save(created[0], expected_version=0)
    await repo.save(created[1], expected_version=0)
    await db_session.flush()

    ready_only, _, _ = await repo.list_by_tenant(
        tenant_id, limit=10, cursor=None, status=AssessmentStatus.READY
    )
    assert len(ready_only) == 2

    page1, cursor1, has_more1 = await repo.list_by_tenant(tenant_id, limit=2, cursor=None)
    assert len(page1) == 2
    assert has_more1 is True
    assert cursor1 is not None

    page2, cursor2, has_more2 = await repo.list_by_tenant(tenant_id, limit=2, cursor=cursor1)
    assert len(page2) == 2
    page1_ids = {str(a.id) for a in page1}
    page2_ids = {str(a.id) for a in page2}
    assert page1_ids.isdisjoint(page2_ids)


async def test_list_by_tenant_scoped_to_tenant(db_session) -> None:  # noqa: ANN001
    tenant_a = TenantId.new()
    tenant_b = TenantId.new()
    repo = SqlAlchemyAssessmentRepository(db_session)

    a1, _ = Assessment.create(
        tenant_id=tenant_a, name="Tenant A", hazard_type=HazardType.FLOOD, created_by=UserId.new()
    )
    b1, _ = Assessment.create(
        tenant_id=tenant_b, name="Tenant B", hazard_type=HazardType.FLOOD, created_by=UserId.new()
    )
    await repo.save(a1)
    await repo.save(b1)
    await db_session.flush()

    tenant_a_results, _, _ = await repo.list_by_tenant(tenant_a, limit=25, cursor=None)
    names = {a.name for a in tenant_a_results}
    assert "Tenant A" in names
    assert "Tenant B" not in names
