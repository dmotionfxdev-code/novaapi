"""Unit tests for ``GoogleEarthEngineProvider``'s config-guard paths —
the parts of Sprint 14's real GEE connector that are reachable WITHOUT
any actual ``ee.Initialize()``/network call, mirroring
``SmtpEmailNotificationChannel``'s "unconfigured means honest immediate
failure" tests. The genuinely-real, network-touching path is exercised
separately by ``tests/integration/test_gee_connectivity.py``, which
skips when no real GEE service account is configured — this file never
imports/calls anything that would require ``ee`` to actually connect.
"""

from __future__ import annotations

import asyncio

import pytest

from georisk.contexts.data_acquisition.application.ports import RemoteSensingFetchSpec
from georisk.contexts.data_acquisition.domain.value_objects import RemoteSensingSource
from georisk.contexts.data_acquisition.infrastructure.gee_connector import (
    _COLLECTION_BY_SOURCE,
    _NATIVE_SCALE_METRES_BY_SOURCE,
    GoogleEarthEngineProvider,
)

pytestmark = pytest.mark.unit


def _spec(**overrides: object) -> RemoteSensingFetchSpec:
    defaults = dict(
        remote_sensing_source=RemoteSensingSource.SENTINEL_2,
        declared_crs="EPSG:4326",
        temporal_start=None,
        temporal_end=None,
        comparison_temporal_start=None,
        comparison_temporal_end=None,
        aoi_geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]},
    )
    defaults.update(overrides)
    return RemoteSensingFetchSpec(**defaults)  # type: ignore[arg-type]


def test_every_remote_sensing_source_has_a_real_collection_id() -> None:
    assert set(_COLLECTION_BY_SOURCE) == set(RemoteSensingSource)
    assert all(collection_id for collection_id in _COLLECTION_BY_SOURCE.values())


def test_every_remote_sensing_source_has_a_native_scale() -> None:
    assert set(_NATIVE_SCALE_METRES_BY_SOURCE) == set(RemoteSensingSource)
    assert all(scale > 0 for scale in _NATIVE_SCALE_METRES_BY_SOURCE.values())


def test_fetch_fails_honestly_when_not_configured() -> None:
    provider = GoogleEarthEngineProvider(
        service_account_email=None, service_account_private_key=None, project_id=None
    )
    result = asyncio.run(provider.fetch(source_reference="ignored", spec=_spec()))
    assert result.success is False
    assert "not configured" in (result.error or "")


def test_fetch_fails_when_spec_missing() -> None:
    provider = GoogleEarthEngineProvider(
        service_account_email="svc@example.iam.gserviceaccount.com",
        service_account_private_key="fake-key-data",
        project_id="fake-project",
    )
    result = asyncio.run(provider.fetch(source_reference="ignored", spec=None))
    assert result.success is False
    assert "remote_sensing_source" in (result.error or "")


def test_fetch_fails_when_remote_sensing_source_missing() -> None:
    provider = GoogleEarthEngineProvider(
        service_account_email="svc@example.iam.gserviceaccount.com",
        service_account_private_key="fake-key-data",
        project_id="fake-project",
    )
    result = asyncio.run(
        provider.fetch(source_reference="ignored", spec=_spec(remote_sensing_source=None))
    )
    assert result.success is False
    assert "remote_sensing_source" in (result.error or "")


def test_fetch_fails_when_aoi_geometry_missing() -> None:
    provider = GoogleEarthEngineProvider(
        service_account_email="svc@example.iam.gserviceaccount.com",
        service_account_private_key="fake-key-data",
        project_id="fake-project",
    )
    result = asyncio.run(
        provider.fetch(source_reference="ignored", spec=_spec(aoi_geometry=None))
    )
    assert result.success is False
    assert "AOI" in (result.error or "")
