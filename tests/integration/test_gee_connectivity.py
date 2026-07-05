"""Sprint 14's "Real GEE connectivity tests where possible" requirement.
Mirrors every other real-infrastructure fixture in this codebase's
established pattern (``api_client``'s ``DATABASE_URL``-absent skip): a
real Google Cloud service account with the Earth Engine API enabled is
required for this test to do anything meaningful, and no such credentials
exist in this platform's sandboxed development/test environments — so
this test SKIPS rather than fails when unconfigured, since "GEE is
unreachable here" is an environment fact, not a code defect. When real
credentials ARE present (``GEE_SERVICE_ACCOUNT_EMAIL``/
``GEE_SERVICE_ACCOUNT_PRIVATE_KEY`` env vars), this exercises a genuine
``ee.Initialize()`` + a real, tiny ``reduceRegion`` call against the
actual Earth Engine API.
"""

from __future__ import annotations

import os

import pytest

from georisk.contexts.data_acquisition.application.ports import RemoteSensingFetchSpec
from georisk.contexts.data_acquisition.domain.value_objects import (
    PreprocessingStep,
    RemoteSensingSource,
)
from georisk.contexts.data_acquisition.infrastructure.gee_connector import (
    GoogleEarthEngineProvider,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def gee_provider() -> GoogleEarthEngineProvider:
    email = os.environ.get("GEE_SERVICE_ACCOUNT_EMAIL")
    private_key = os.environ.get("GEE_SERVICE_ACCOUNT_PRIVATE_KEY")
    if not email or not private_key:
        pytest.skip(
            "GEE_SERVICE_ACCOUNT_EMAIL/GEE_SERVICE_ACCOUNT_PRIVATE_KEY not set — "
            "real Google Earth Engine connectivity tests need a real GCP service "
            "account with the Earth Engine API enabled"
        )
    return GoogleEarthEngineProvider(
        service_account_email=email,
        service_account_private_key=private_key,
        project_id=os.environ.get("GEE_PROJECT_ID"),
    )


async def test_real_gee_fetch_returns_band_statistics_over_a_small_aoi(
    gee_provider: GoogleEarthEngineProvider,
) -> None:
    # A small, fixed AOI (~1km^2 near the equator) so a real fetch stays cheap.
    spec = RemoteSensingFetchSpec(
        remote_sensing_source=RemoteSensingSource.SENTINEL_2,
        declared_crs="EPSG:4326",
        temporal_start=None,
        temporal_end=None,
        comparison_temporal_start=None,
        comparison_temporal_end=None,
        aoi_geometry={
            "type": "Polygon",
            "coordinates": [
                [[36.80, -1.30], [36.80, -1.29], [36.81, -1.29], [36.81, -1.30], [36.80, -1.30]]
            ],
        },
        requested_preprocessing=(PreprocessingStep.RADIOMETRIC_CORRECTION,),
    )
    result = await gee_provider.fetch(source_reference="ignored", spec=spec)
    assert result.success is True, result.error
    assert result.content is not None
    assert result.band_statistics is not None
    assert "B4" in result.band_statistics
