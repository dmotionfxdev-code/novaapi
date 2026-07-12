"""Unit tests for ``GoogleEarthEngineProvider``'s config-guard paths —
the parts of Sprint 14's real GEE connector that are reachable WITHOUT
any actual ``ee.Initialize()``/network call, mirroring
``SmtpEmailNotificationChannel``'s "unconfigured means honest immediate
failure" tests. The genuinely-real, network-touching path is exercised
separately by ``tests/integration/test_gee_connectivity.py``, which
skips when no real GEE service account is configured — this file never
imports/calls anything that would require ``ee`` to actually connect.

Also covers the post-RC1 bug fix making the raw raster download an
optional, best-effort artifact of a GEE fetch (real Earth Engine's
``getDownloadURL`` has a fixed synchronous request-size limit that any
AOI larger than a small test square exceeds at native resolution; the
real, useful output — ``band_statistics``/extracted features — comes
entirely from ``reduceRegion``, computed and already safe before the
download is even attempted). The two scenario tests below mock
``_build_composite``/``ee.Geometry`` (confirmed empirically that
``ee.Geometry`` itself requires a real ``ee.Initialize()`` to construct
at all — not assumed) rather than touching real Earth Engine, so they
run in every environment, not just where real GEE credentials exist;
the real-network proof lives in
``tests/integration/test_gee_connectivity.py``.
"""

from __future__ import annotations

import asyncio
from unittest import mock

import ee
import pytest

from georisk.contexts.data_acquisition.application.ports import RemoteSensingFetchSpec
from georisk.contexts.data_acquisition.domain.value_objects import (
    PreprocessingStep,
    RemoteSensingSource,
)
from georisk.contexts.data_acquisition.infrastructure.gee_connector import (
    _COLLECTION_BY_SOURCE,
    _NATIVE_SCALE_METRES_BY_SOURCE,
    GoogleEarthEngineProvider,
    _is_request_size_limit_error,
    _mask_landsat_clouds,
    _mask_sentinel2_clouds,
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


# --- Bug fix (post-RC1 Production Acceptance Test): raster download is an
# optional artifact, not a hard requirement for a successful GEE fetch --------


def test_is_request_size_limit_error_matches_the_real_observed_message() -> None:
    """Exact text Earth Engine returned when this was reproduced live
    against the real API during the RC1 Production Acceptance Test — not
    a guessed format."""
    real_message = (
        "Total request size (1160529786 bytes) must be less than or equal to "
        "50331648 bytes."
    )
    assert _is_request_size_limit_error(ee.EEException(real_message)) is True


def test_is_request_size_limit_error_rejects_unrelated_eeexceptions() -> None:
    """A different, real Earth Engine failure must never be mistaken for
    the specific request-size-limit case — requirement #3's "specifically
    detect," not "catch anything that looks vaguely similar."""
    not_found = ee.EEException("Image.load: Image asset not found.")
    memory_limit = ee.EEException("User memory limit exceeded.")
    assert _is_request_size_limit_error(not_found) is False
    assert _is_request_size_limit_error(memory_limit) is False


def test_fetch_propagates_a_genuine_reduceregion_failure_without_being_swallowed() -> None:
    """The download-only try/except this bug fix adds must never mask a
    real Earth Engine failure that happens BEFORE the download step (the
    reduceRegion calls, requirement #7). A fake ``image`` whose
    ``reduceRegion(...).getInfo()`` raises a real ``ee.EEException`` with a
    message that does NOT match the request-size-limit signature proves
    the exception reaches ``fetch()``'s existing outer handler (a FAILED
    result) — the new except block, scoped strictly to the download call
    placed textually after both reduceRegion calls, never even runs.
    """

    class _FailingImage:
        def reduceRegion(self, **_kwargs: object) -> _FailingImage:
            return self

        def getInfo(self) -> None:
            raise ee.EEException("Image.reduceRegion: User memory limit exceeded.")

    provider = GoogleEarthEngineProvider(
        service_account_email="svc@example.iam.gserviceaccount.com",
        service_account_private_key="fake-key-data",
        project_id="fake-project",
    )
    provider._initialized = True  # skip the real ee.Initialize() call

    with mock.patch.object(
        GoogleEarthEngineProvider, "_build_composite", return_value=(_FailingImage(), [])
    ), mock.patch(
        "georisk.contexts.data_acquisition.infrastructure.gee_connector.ee.Geometry",
        return_value=object(),
    ), mock.patch(
        # ee.Reducer.mean() is itself a real, unmocked Earth Engine call
        # made while BUILDING the reduceRegion(...) call's own keyword
        # arguments — it runs (and would fail with the same "not
        # initialized" error) before Python ever calls the fake image's
        # reduceRegion() method, regardless of what that fake returns.
        # Confirmed empirically (a real traceback through
        # ee.apifunction.ApiFunction.lookup -> data.getAlgorithms) before
        # adding this — not assumed.
        "georisk.contexts.data_acquisition.infrastructure.gee_connector.ee.Reducer"
    ):
        result = asyncio.run(provider.fetch(source_reference="ignored", spec=_spec()))

    assert result.success is False
    assert "User memory limit exceeded" in (result.error or "")
    assert result.content is None
    assert result.raster_skipped_reason is None


def test_fetch_skips_raster_download_and_still_succeeds_on_size_limit_error() -> None:
    """The core proof of this bug fix: a fake ``image`` whose
    ``reduceRegion`` succeeds (real band statistics) but whose
    ``getDownloadURL`` raises the exact real request-size-limit
    ``EEException`` still produces a successful ``FetchResult`` — content
    is honestly ``None`` (never a fabricated placeholder), and
    ``raster_skipped_reason`` carries the real reason.
    """

    class _OversizedImage:
        def reduceRegion(self, **_kwargs: object) -> _OversizedImage:
            return self

        def getInfo(self) -> dict[str, float]:
            return {"B4": 0.12, "B8": 0.34}

        def getDownloadURL(self, _params: dict) -> str:
            raise ee.EEException(
                "Total request size (1160529786 bytes) must be less than or "
                "equal to 50331648 bytes."
            )

    provider = GoogleEarthEngineProvider(
        service_account_email="svc@example.iam.gserviceaccount.com",
        service_account_private_key="fake-key-data",
        project_id="fake-project",
    )
    provider._initialized = True

    with mock.patch.object(
        GoogleEarthEngineProvider, "_build_composite", return_value=(_OversizedImage(), [])
    ), mock.patch(
        "georisk.contexts.data_acquisition.infrastructure.gee_connector.ee.Geometry",
        return_value=object(),
    ), mock.patch(
        "georisk.contexts.data_acquisition.infrastructure.gee_connector.ee.Reducer"
    ):
        result = asyncio.run(provider.fetch(source_reference="ignored", spec=_spec()))

    assert result.success is True, result.error
    assert result.content is None
    assert result.band_statistics == {"B4": 0.12, "B8": 0.34}
    assert result.raster_skipped_reason is not None
    assert "request-size limit" in result.raster_skipped_reason


# --- Bug fix: Image.bitwiseAnd: Bitwise operands must be integer only -------
#
# Root cause: ee.ImageCollection.median() always returns FLOAT-typed bands
# for every band, including QA60/QA_PIXEL bitmask bands, regardless of the
# source bands' integer type — a well-documented, real Earth Engine
# behaviour, not specific to this codebase. Cloud masking was previously
# applied AFTER .median() compositing, in _apply_preprocessing(), so its
# QA-band .bitwiseAnd() calls crashed against the composite's float-typed
# QA band. The fix moves masking to run per-image, via
# ee.ImageCollection.map(...), BEFORE .median() — proven below by asserting
# the actual call order on a fake collection, not just that some masking
# function exists somewhere in the module.


class _FakeCollection:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.mapped_with: list[object] = []

    def filterBounds(self, _region: object) -> _FakeCollection:
        self.calls.append("filterBounds")
        return self

    def filterDate(self, _start: str, _end: str) -> _FakeCollection:
        self.calls.append("filterDate")
        return self

    def map(self, fn: object) -> _FakeCollection:
        self.calls.append("map")
        self.mapped_with.append(fn)
        return self

    def median(self) -> object:
        self.calls.append("median")
        return object()


def test_build_composite_masks_sentinel2_clouds_via_map_before_median() -> None:
    fake_collection = _FakeCollection()
    provider = GoogleEarthEngineProvider(
        service_account_email="svc@example.iam.gserviceaccount.com",
        service_account_private_key="fake-key-data",
        project_id="fake-project",
    )

    with mock.patch(
        "georisk.contexts.data_acquisition.infrastructure.gee_connector.ee.ImageCollection",
        return_value=fake_collection,
    ):
        _image, applied = provider._build_composite(
            source=RemoteSensingSource.SENTINEL_2,
            region=object(),
            declared_crs="EPSG:4326",
            temporal_start=None,
            temporal_end=None,
            requested_preprocessing=(PreprocessingStep.CLOUD_MASKING,),
        )

    assert fake_collection.calls == ["filterBounds", "map", "median"]
    assert fake_collection.mapped_with == [_mask_sentinel2_clouds]
    assert applied == [PreprocessingStep.CLOUD_MASKING]


def test_build_composite_masks_landsat_clouds_via_map_before_median() -> None:
    fake_collection = _FakeCollection()
    provider = GoogleEarthEngineProvider(
        service_account_email="svc@example.iam.gserviceaccount.com",
        service_account_private_key="fake-key-data",
        project_id="fake-project",
    )

    with mock.patch(
        "georisk.contexts.data_acquisition.infrastructure.gee_connector.ee.ImageCollection",
        return_value=fake_collection,
    ):
        _image, applied = provider._build_composite(
            source=RemoteSensingSource.LANDSAT,
            region=object(),
            declared_crs="EPSG:4326",
            temporal_start=None,
            temporal_end=None,
            requested_preprocessing=(PreprocessingStep.CLOUD_MASKING,),
        )

    assert fake_collection.calls == ["filterBounds", "map", "median"]
    assert fake_collection.mapped_with == [_mask_landsat_clouds]
    assert applied == [PreprocessingStep.CLOUD_MASKING]


def test_build_composite_skips_map_when_cloud_masking_not_requested() -> None:
    """No CLOUD_MASKING in the requested steps must mean .map() is never
    called at all — not called-with-a-noop — proving this is a real
    conditional wire-up, not always-on masking."""
    fake_collection = _FakeCollection()
    provider = GoogleEarthEngineProvider(
        service_account_email="svc@example.iam.gserviceaccount.com",
        service_account_private_key="fake-key-data",
        project_id="fake-project",
    )

    with mock.patch(
        "georisk.contexts.data_acquisition.infrastructure.gee_connector.ee.ImageCollection",
        return_value=fake_collection,
    ):
        _image, applied = provider._build_composite(
            source=RemoteSensingSource.SENTINEL_2,
            region=object(),
            declared_crs="EPSG:4326",
            temporal_start=None,
            temporal_end=None,
            requested_preprocessing=(),
        )

    assert fake_collection.calls == ["filterBounds", "median"]
    assert applied == []


def test_build_composite_leaves_modis_cloud_masking_honestly_unapplied() -> None:
    """MODIS has no usable QA band wired into this pipeline (see the
    module docstring) — requesting CLOUD_MASKING for it must not silently
    fabricate an "applied" claim, and must not call .map() either."""
    fake_collection = _FakeCollection()
    provider = GoogleEarthEngineProvider(
        service_account_email="svc@example.iam.gserviceaccount.com",
        service_account_private_key="fake-key-data",
        project_id="fake-project",
    )

    with mock.patch(
        "georisk.contexts.data_acquisition.infrastructure.gee_connector.ee.ImageCollection",
        return_value=fake_collection,
    ):
        _image, applied = provider._build_composite(
            source=RemoteSensingSource.MODIS,
            region=object(),
            declared_crs="EPSG:4326",
            temporal_start=None,
            temporal_end=None,
            requested_preprocessing=(PreprocessingStep.CLOUD_MASKING,),
        )

    assert fake_collection.calls == ["filterBounds", "median"]
    assert applied == []
