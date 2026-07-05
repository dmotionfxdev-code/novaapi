"""Handler-level integration tests against a real Postgres instance —
``DefineOrReviseAoiHandler``, ``ConfigureSamplingCampaignHandler``, and
``GenerateSamplePointsHandler``'s gather -> compute -> persist -> emit
pipeline.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from georisk.contexts.geospatial.application.commands import (
    ConfigureSamplingCampaignCommand,
    DefineOrReviseAoiCommand,
    GenerateSamplePointsCommand,
)
from georisk.contexts.geospatial.application.handlers import (
    ConfigureSamplingCampaignHandler,
    DefineOrReviseAoiHandler,
    GenerateSamplePointsHandler,
)
from georisk.contexts.geospatial.domain.value_objects import AoiStatus, SamplingCampaignStatus
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.db.outbox_models import OutboxEventModel

pytestmark = pytest.mark.integration

_SQUARE_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]],
}


async def test_define_aoi_then_revise_supersedes_first_version(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = DefineOrReviseAoiHandler(db_session)

    first = await handler.handle(
        DefineOrReviseAoiCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            source="DRAWN",
            geojson=_SQUARE_GEOJSON,
            name="Initial AOI",
            notes="",
            issued_by="analyst-1",
        )
    )
    assert first.version == 1
    assert first.status == AoiStatus.ACTIVE

    second = await handler.handle(
        DefineOrReviseAoiCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            source="DRAWN",
            geojson=_SQUARE_GEOJSON,
            name="Revised AOI",
            notes="updated",
            issued_by="analyst-1",
        )
    )
    assert second.version == 2
    assert second.status == AoiStatus.ACTIVE

    outbox = await db_session.execute(
        select(OutboxEventModel).where(OutboxEventModel.aggregate_type == "AreaOfInterest")
    )
    event_types = {e.event_type for e in outbox.scalars().all()}
    assert event_types == {"geospatial.AoiAttached", "geospatial.AoiRevised"}


async def test_configure_and_generate_sampling_campaign(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    aoi_handler = DefineOrReviseAoiHandler(db_session)
    aoi = await aoi_handler.handle(
        DefineOrReviseAoiCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            source="DRAWN",
            geojson=_SQUARE_GEOJSON,
            name="AOI",
            notes="",
            issued_by="analyst-1",
        )
    )

    configure_handler = ConfigureSamplingCampaignHandler(db_session)
    campaign = await configure_handler.handle(
        ConfigureSamplingCampaignCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            aoi_id=str(aoi.id),
            name="Campaign 1",
            method="STRATIFIED_RANDOM",
            sample_size=1000,
            strata=({"label": "forest", "proportion": 0.6}, {"label": "urban", "proportion": 0.4}),
            issued_by="analyst-1",
        )
    )
    assert campaign.status == SamplingCampaignStatus.DRAFT
    assert len(campaign.sample_points) == 0

    generate_handler = GenerateSamplePointsHandler(db_session)
    generated = await generate_handler.handle(
        GenerateSamplePointsCommand(
            tenant_id=str(tenant_id), sampling_campaign_id=str(campaign.id), issued_by="analyst-1"
        )
    )
    assert generated.status == SamplingCampaignStatus.GENERATED
    assert len(generated.sample_points) == 1000

    outbox = await db_session.execute(
        select(OutboxEventModel).where(OutboxEventModel.aggregate_type == "SamplingCampaign")
    )
    event_types = {e.event_type for e in outbox.scalars().all()}
    assert event_types == {
        "geospatial.SamplingCampaignConfigured",
        "geospatial.SamplePointsGenerated",
    }
