"""Repository-level integration tests against a real Postgres instance —
confirms the Geospatial context's domain<->ORM mapping round-trips
correctly.
"""

from __future__ import annotations

import uuid

import pytest

from georisk.contexts.geospatial.domain.entities import AreaOfInterest, SamplingCampaign
from georisk.contexts.geospatial.domain.value_objects import (
    AoiMetadata,
    AoiSource,
    AoiStatus,
    Geometry,
    SamplingMethod,
    SamplingStrategy,
)
from georisk.contexts.geospatial.infrastructure.repositories import (
    SqlAlchemyAreaOfInterestRepository,
    SqlAlchemySamplingCampaignRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId

pytestmark = pytest.mark.integration

_SQUARE = Geometry(
    geojson={
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]],
    }
)


async def test_aoi_save_and_get_round_trips(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    aoi, _ = AreaOfInterest.define(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        geometry=_SQUARE,
        metadata=AoiMetadata(name="Test AOI", source=AoiSource.DRAWN),
        created_by="analyst-1",
    )
    repo = SqlAlchemyAreaOfInterestRepository(db_session)
    await repo.save(aoi)
    await db_session.flush()

    fetched = await repo.get_by_id(aoi.id)
    assert fetched is not None
    assert fetched.status == AoiStatus.ACTIVE
    assert fetched.geometry.geojson == _SQUARE.geojson
    assert fetched.metadata.name == "Test AOI"
    assert fetched.area_m2 == pytest.approx(aoi.area_m2)


async def test_aoi_get_active_for_assessment_ignores_superseded(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    repo = SqlAlchemyAreaOfInterestRepository(db_session)

    first, _ = AreaOfInterest.define(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        geometry=_SQUARE,
        metadata=AoiMetadata(name="V1", source=AoiSource.DRAWN),
        created_by="analyst-1",
    )
    await repo.save(first)
    await db_session.flush()

    second, _ = AreaOfInterest.revise(
        previous=first,
        geometry=_SQUARE,
        metadata=AoiMetadata(name="V2", source=AoiSource.DRAWN),
        created_by="analyst-1",
    )
    first.mark_superseded()
    await repo.save(first)
    await repo.save(second)
    await db_session.flush()

    active = await repo.get_active_for_assessment(tenant_id, assessment_id)
    assert active is not None
    assert active.version == 2
    assert active.metadata.name == "V2"

    versions = await repo.list_versions(tenant_id, assessment_id)
    assert [v.version for v in versions] == [1, 2]


async def test_sampling_campaign_save_and_get_round_trips(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    aoi, _ = AreaOfInterest.define(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        geometry=_SQUARE,
        metadata=AoiMetadata(name="AOI", source=AoiSource.DRAWN),
        created_by="analyst-1",
    )
    aoi_repo = SqlAlchemyAreaOfInterestRepository(db_session)
    await aoi_repo.save(aoi)
    await db_session.flush()

    campaign, _ = SamplingCampaign.configure(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        aoi_id=aoi.id,
        name="Campaign 1",
        strategy=SamplingStrategy(method=SamplingMethod.SIMPLE_RANDOM, sample_size=1000),
        created_by="analyst-1",
    )
    campaign.generate_points(aoi_geometry=aoi.geometry)

    campaign_repo = SqlAlchemySamplingCampaignRepository(db_session)
    await campaign_repo.save(campaign)
    await db_session.flush()

    fetched = await campaign_repo.get_by_id(campaign.id)
    assert fetched is not None
    assert len(fetched.sample_points) == 1000
    assert fetched.strategy.sample_size == 1000

    listed = await campaign_repo.list_by_assessment(tenant_id, assessment_id)
    assert len(listed) == 1
