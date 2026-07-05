"""Domain-layer unit tests for the Geospatial context's aggregates —
pure logic, no I/O.
"""

from __future__ import annotations

import uuid

import pytest

from georisk.contexts.geospatial.domain.entities import AreaOfInterest, SamplingCampaign
from georisk.contexts.geospatial.domain.errors import (
    SamplingNotConfiguredError,
)
from georisk.contexts.geospatial.domain.value_objects import (
    AoiId,
    AoiMetadata,
    AoiSource,
    AoiStatus,
    Geometry,
    SamplingCampaignStatus,
    SamplingMethod,
    SamplingStrategy,
    Stratum,
)
from georisk.contexts.identity.domain.value_objects import TenantId

pytestmark = pytest.mark.unit

_SQUARE = Geometry(
    geojson={
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]],
    }
)
_OTHER_SQUARE = Geometry(
    geojson={
        "type": "Polygon",
        "coordinates": [[[5.0, 5.0], [5.0, 6.0], [6.0, 6.0], [6.0, 5.0], [5.0, 5.0]]],
    }
)


def _metadata(name: str = "Test AOI") -> AoiMetadata:
    return AoiMetadata(name=name, source=AoiSource.DRAWN)


def test_define_aoi_produces_active_version_one_and_event() -> None:
    aoi, event = AreaOfInterest.define(
        tenant_id=TenantId.new(),
        assessment_id=str(uuid.uuid4()),
        geometry=_SQUARE,
        metadata=_metadata(),
        created_by="analyst-1",
    )
    assert aoi.version == 1
    assert aoi.status == AoiStatus.ACTIVE
    assert aoi.area_m2 > 0
    assert event.event_type == "geospatial.AoiAttached"
    assert event.version == 1


def test_revise_aoi_creates_a_new_version_and_supersedes_the_old() -> None:
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    first, _ = AreaOfInterest.define(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        geometry=_SQUARE,
        metadata=_metadata(),
        created_by="analyst-1",
    )
    second, event = AreaOfInterest.revise(
        previous=first,
        geometry=_OTHER_SQUARE,
        metadata=_metadata("Revised AOI"),
        created_by="analyst-2",
    )
    first.mark_superseded()

    assert second.version == 2
    assert second.status == AoiStatus.ACTIVE
    assert first.status == AoiStatus.SUPERSEDED
    assert second.id != first.id
    assert event.superseded_aoi_id == str(first.id)


def test_configure_stratified_campaign_requires_strata() -> None:
    with pytest.raises(SamplingNotConfiguredError):
        SamplingCampaign.configure(
            tenant_id=TenantId.new(),
            assessment_id=str(uuid.uuid4()),
            aoi_id=AoiId.new(),
            name="Campaign",
            strategy=SamplingStrategy(method=SamplingMethod.STRATIFIED_RANDOM),
            strata=(),
            created_by="analyst-1",
        )


def test_generate_points_produces_points_matching_sample_size() -> None:
    campaign, _ = SamplingCampaign.configure(
        tenant_id=TenantId.new(),
        assessment_id=str(uuid.uuid4()),
        aoi_id=AoiId.new(),
        name="Campaign",
        strategy=SamplingStrategy(method=SamplingMethod.SIMPLE_RANDOM, sample_size=1000),
        created_by="analyst-1",
    )
    event = campaign.generate_points(aoi_geometry=_SQUARE)
    assert campaign.status == SamplingCampaignStatus.GENERATED
    assert len(campaign.sample_points) == 1000
    assert event.sample_count == 1000


def test_generate_points_twice_raises() -> None:
    campaign, _ = SamplingCampaign.configure(
        tenant_id=TenantId.new(),
        assessment_id=str(uuid.uuid4()),
        aoi_id=AoiId.new(),
        name="Campaign",
        strategy=SamplingStrategy(method=SamplingMethod.SIMPLE_RANDOM, sample_size=1000),
        created_by="analyst-1",
    )
    campaign.generate_points(aoi_geometry=_SQUARE)
    with pytest.raises(SamplingNotConfiguredError):
        campaign.generate_points(aoi_geometry=_SQUARE)


def test_stratified_campaign_generates_labeled_points() -> None:
    campaign, _ = SamplingCampaign.configure(
        tenant_id=TenantId.new(),
        assessment_id=str(uuid.uuid4()),
        aoi_id=AoiId.new(),
        name="Campaign",
        strategy=SamplingStrategy(method=SamplingMethod.STRATIFIED_RANDOM, sample_size=1000),
        strata=(Stratum(label="forest", proportion=0.5), Stratum(label="urban", proportion=0.5)),
        created_by="analyst-1",
    )
    campaign.generate_points(aoi_geometry=_SQUARE)
    labels = {p.stratum for p in campaign.sample_points}
    assert labels == {"forest", "urban"}
