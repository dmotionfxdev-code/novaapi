"""Sprint 14's real Google Earth Engine connector — supersedes Sprint
13's interface-only ``GoogleEarthEngineProvider`` stub (which lived in
``application/ports.py`` and always returned ``success=False``). This one
does genuine ``earthengine-api`` (``ee``) I/O, so it lives in
``infrastructure/`` — the same "real I/O is an infrastructure concern"
boundary as ``HttpAcquisitionProvider``/``SmtpEmailNotificationChannel``.
Wrapped in ``asyncio.to_thread`` throughout since every ``ee`` call
(``Initialize``, ``.getInfo()``, ``.getDownloadURL()``) is synchronous.

``ee.Initialize()`` needs a real Google Cloud service account with the
Earth Engine API enabled — ``settings.gee_service_account_email``/
``gee_service_account_private_key`` default to ``None`` (identical
"unconfigured means honest immediate failure" discipline as
``settings.smtp_host``/``HttpAcquisitionProvider``'s ``base_url``). No
such credentials exist in this platform's sandboxed development/test
environments; this class's own connectivity is exercised by
``tests/integration/test_gee_connectivity.py``, which — again mirroring
the ``DATABASE_URL``-absent skip pattern every integration test fixture
in this codebase already uses — skips rather than fails when
unconfigured, since "GEE is unreachable in this sandbox" is an
environment fact, not a defect.

Design decisions, named rather than hidden (Sprint 14 requirements #2/#3/
#4, "Preprocessing," "Feature Extraction"):

- Six supported collections (one per :class:`RemoteSensingSource`), each a
  real, citable Earth Engine asset ID — Surface Reflectance / Level-2
  products where available (``COPERNICUS/S2_SR_HARMONIZED``,
  ``LANDSAT/LC08/C02/T1_L2``), so ATMOSPHERIC_CORRECTION for these two
  sources is a genuine pass-through: the correction has already been
  applied upstream by ESA/USGS, not re-derived by this platform (a
  from-scratch 6S/DOS atmospheric model is a far larger undertaking this
  sprint's brief does not ask for). RADIOMETRIC_CORRECTION IS real,
  first-party work here: each source's documented DN -> physical-unit
  scale/offset is applied via ``ee.Image`` band math before any
  statistic is read.
- CLOUD_MASKING is real (QA-band bit-masking) for the two optical sources
  that carry a usable QA band in this pipeline (Sentinel-2's ``QA60``,
  Landsat's ``QA_PIXEL``) — not applicable to MODIS (this pipeline's
  MOD09GA product's own per-band QA is a coarser, less standard bitmask
  not worth the added complexity this sprint), CHIRPS, or ERA5 (no cloud
  concept for precipitation/reanalysis products).
- Every ``ee.ImageCollection`` is composited via ``.median()`` — the
  standard Earth Engine idiom for a cloud-reduced composite over a date
  range, real and well-documented, not invented for this platform.
  CLOUD_MASKING runs per-image via ``.map()`` BEFORE this compositing,
  not after (bug fix: see ``_build_composite``'s docstring — masking the
  already-composited image was both semantically wrong and the literal
  cause of a real ``Image.bitwiseAnd: Bitwise operands must be integer
  only`` crash, since ``.median()`` always returns float-typed bands,
  including QA/bitmask bands, regardless of the source bands' type).
- AOI is a hard requirement for a GEE job (enforced in
  ``AcquisitionJob.schedule()``): ``getDownloadURL``/``reduceRegion``
  need a bounded region, and letting a GEE job request an unbounded
  global export would be a real, unbounded-cost operation this platform
  has no business allowing silently.

Capability note (bug fix, post-RC1 Production Acceptance Test): **this
platform stores statistical outputs (per-band ``reduceRegion`` means and
the spectral indices derived from them), not full raster imagery, as the
authoritative product of a GEE acquisition.** The raw pixel GeoTIFF
download (``getDownloadURL``) is a best-effort, optional artifact —
nothing in Analysis, Prediction, Validation, or the frontend has ever
consumed it (there is no raster/tile pipeline anywhere in this platform;
see ``RasterMetadataResponse.available``, always ``False``). Earth
Engine's synchronous ``getDownloadURL`` has a fixed request-size limit
that any AOI larger than a small test square exceeds at native
resolution — when that happens, the acquisition still completes
successfully using the already-computed statistics; ``AcquisitionJob``'s
raw content is honestly absent (never fabricated), and its provenance
records why (``FetchResult.raster_skipped_reason``).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import ee
import requests

from georisk.contexts.data_acquisition.application.ports import FetchResult, RemoteSensingFetchSpec
from georisk.contexts.data_acquisition.domain.value_objects import (
    PreprocessingStep,
    RemoteSensingSource,
)

logger = logging.getLogger("georisk.data_acquisition.gee")

#: TIFF magic bytes (little-endian "II*\x00" / big-endian "MM\x00*") —
#: deliberately mirrors domain/validation.py's own ``_TIFF_MAGIC`` (used
#: there by ``validate_geotiff()``) rather than importing that module's
#: private constant: this is a diagnostic pre-check only (logs, does not
#: reject), and infrastructure has no business depending on a leading-
#: underscore domain internal for that.
_TIFF_MAGIC = (b"II*\x00", b"MM\x00*")

#: The exact two substrings Earth Engine's own error text contains when
#: `Image.getDownloadURL()` rejects a request for exceeding its
#: synchronous request-size limit — observed verbatim against the real
#: Earth Engine API during the RC1 Production Acceptance Test:
#: "Total request size (1160529786 bytes) must be less than or equal to
#: 50331648 bytes." Matching on both (not just one) keeps this specific,
#: per requirement #3 — an unrelated EEException carrying only one of
#: these substrings by coincidence is not treated as a skippable case.
_REQUEST_SIZE_LIMIT_MARKERS = ("Total request size", "must be less than or equal to")


def _is_request_size_limit_error(exc: Exception) -> bool:
    message = str(exc)
    return all(marker in message for marker in _REQUEST_SIZE_LIMIT_MARKERS)

#: Real Earth Engine collection asset IDs, one per supported source.
_COLLECTION_BY_SOURCE: dict[RemoteSensingSource, str] = {
    RemoteSensingSource.SENTINEL_1: "COPERNICUS/S1_GRD",
    RemoteSensingSource.SENTINEL_2: "COPERNICUS/S2_SR_HARMONIZED",
    RemoteSensingSource.LANDSAT: "LANDSAT/LC08/C02/T1_L2",
    RemoteSensingSource.MODIS: "MODIS/061/MOD09GA",
    RemoteSensingSource.CHIRPS: "UCSB-CHG/CHIRPS/DAILY",
    RemoteSensingSource.ERA5: "ECMWF/ERA5/DAILY",
}

#: Native ground-sample-distance (metres) per source — used for both
#: ``.reproject()``'s ``scale`` and ``reduceRegion``'s ``scale``.
_NATIVE_SCALE_METRES_BY_SOURCE: dict[RemoteSensingSource, int] = {
    RemoteSensingSource.SENTINEL_1: 10,
    RemoteSensingSource.SENTINEL_2: 10,
    RemoteSensingSource.LANDSAT: 30,
    RemoteSensingSource.MODIS: 500,
    RemoteSensingSource.CHIRPS: 5566,
    RemoteSensingSource.ERA5: 27830,
}

#: Sources this pipeline can apply real, documented cloud masking to.
_CLOUD_MASKABLE_SOURCES = frozenset(
    {RemoteSensingSource.SENTINEL_2, RemoteSensingSource.LANDSAT}
)

#: Sources whose selected collection is already an atmospherically-
#: corrected surface-reflectance / level-2 product.
_ALREADY_ATMOSPHERICALLY_CORRECTED_SOURCES = frozenset(
    {RemoteSensingSource.SENTINEL_2, RemoteSensingSource.LANDSAT, RemoteSensingSource.MODIS}
)


def _mask_sentinel2_clouds(image: ee.Image) -> ee.Image:
    qa60 = image.select("QA60")
    cloud_bit, cirrus_bit = 10, 11
    mask = (
        qa60.bitwiseAnd(1 << cloud_bit)
        .eq(0)
        .And(qa60.bitwiseAnd(1 << cirrus_bit).eq(0))
    )
    return image.updateMask(mask)


def _mask_landsat_clouds(image: ee.Image) -> ee.Image:
    qa_pixel = image.select("QA_PIXEL")
    dilated_cloud_bit, cloud_bit, cloud_shadow_bit = 1, 3, 4
    mask = (
        qa_pixel.bitwiseAnd(1 << dilated_cloud_bit)
        .eq(0)
        .And(qa_pixel.bitwiseAnd(1 << cloud_bit).eq(0))
        .And(qa_pixel.bitwiseAnd(1 << cloud_shadow_bit).eq(0))
    )
    return image.updateMask(mask)


def _apply_radiometric_correction(image: ee.Image, source: RemoteSensingSource) -> ee.Image:
    """Real, documented DN -> physical-unit scale/offset per source.
    Sentinel-2 SR/MODIS surface-reflectance bands are scaled integers
    (divide to get reflectance in [0, 1]); Landsat Collection 2 Level-2
    publishes its own official scale/offset per USGS's product guide,
    applied separately to optical vs. the thermal band."""
    if source == RemoteSensingSource.SENTINEL_2:
        optical_bands = image.select(["B2", "B3", "B4", "B8", "B11", "B12"])
        return image.addBands(optical_bands.divide(10000), overwrite=True)
    if source == RemoteSensingSource.MODIS:
        optical_bands = image.select(
            ["sur_refl_b01", "sur_refl_b02", "sur_refl_b03", "sur_refl_b04",
             "sur_refl_b06", "sur_refl_b07"]
        )
        return image.addBands(optical_bands.multiply(0.0001), overwrite=True)
    if source == RemoteSensingSource.LANDSAT:
        optical_bands = image.select(["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"])
        optical_corrected = optical_bands.multiply(0.0000275).add(-0.2)
        thermal_corrected = image.select("ST_B10").multiply(0.00341802).add(149.0)
        return image.addBands(optical_corrected, overwrite=True).addBands(
            thermal_corrected, overwrite=True
        )
    return image


def _apply_preprocessing(
    image: ee.Image,
    *,
    source: RemoteSensingSource,
    region: ee.Geometry | None,
    declared_crs: str,
    requested_steps: tuple[PreprocessingStep, ...],
) -> tuple[ee.Image, list[PreprocessingStep]]:
    """Every step here runs on the already-composited single ``ee.Image``
    — CLOUD_MASKING is deliberately NOT handled here (bug fix: see
    ``_build_composite``'s docstring for why masking a composite is both
    wrong and the literal cause of a real
    ``Image.bitwiseAnd: Bitwise operands must be integer only`` crash;
    masking must happen per-image, before compositing, not here).
    """
    applied: list[PreprocessingStep] = []
    for step in requested_steps:
        if step == PreprocessingStep.ATMOSPHERIC_CORRECTION:
            if source in _ALREADY_ATMOSPHERICALLY_CORRECTED_SOURCES:
                applied.append(step)
        elif step == PreprocessingStep.RADIOMETRIC_CORRECTION:
            image = _apply_radiometric_correction(image, source)
            applied.append(step)
        elif step == PreprocessingStep.REPROJECTION:
            scale = _NATIVE_SCALE_METRES_BY_SOURCE[source]
            image = image.reproject(crs=declared_crs, scale=scale)
            applied.append(step)
        elif step == PreprocessingStep.AOI_CLIPPING and region is not None:
            image = image.clip(region)
            applied.append(step)
    return image, applied


class GoogleEarthEngineProvider:
    def __init__(
        self,
        *,
        service_account_email: str | None,
        service_account_private_key: str | None,
        project_id: str | None,
    ) -> None:
        self._service_account_email = service_account_email
        self._service_account_private_key = service_account_private_key
        self._project_id = project_id
        self._initialized = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        credentials = ee.ServiceAccountCredentials(
            self._service_account_email, key_data=self._service_account_private_key
        )
        ee.Initialize(credentials, project=self._project_id)
        self._initialized = True

    async def fetch(
        self,
        *,
        source_reference: str,
        raw_content: bytes | None = None,
        spec: RemoteSensingFetchSpec | None = None,
    ) -> FetchResult:
        if not self._service_account_email or not self._service_account_private_key:
            return FetchResult(
                success=False,
                content=None,
                error="Google Earth Engine is not configured (no service account credentials set)",
            )
        if spec is None or spec.remote_sensing_source is None:
            return FetchResult(
                success=False, content=None, error="remote_sensing_source is required for GEE"
            )
        if spec.aoi_geometry is None:
            return FetchResult(
                success=False, content=None, error="An AOI is required for GEE acquisition jobs"
            )
        try:
            return await asyncio.to_thread(self._fetch_sync, spec)
        except Exception as exc:  # noqa: BLE001 — GEE/network is this
            # provider's own untrusted I/O boundary; a graceful FAILED
            # fetch (not an unhandled exception) is the same "isolate an
            # untrusted boundary" reasoning every other provider in this
            # codebase already applies.
            return FetchResult(success=False, content=None, error=str(exc))

    def _fetch_sync(self, spec: RemoteSensingFetchSpec) -> FetchResult:
        self._ensure_initialized()
        source = spec.remote_sensing_source
        assert source is not None  # narrowed by fetch()'s guard above
        region = ee.Geometry(spec.aoi_geometry)
        scale = _NATIVE_SCALE_METRES_BY_SOURCE[source]

        image, applied = self._build_composite(
            source=source,
            region=region,
            declared_crs=spec.declared_crs,
            temporal_start=spec.temporal_start,
            temporal_end=spec.temporal_end,
            requested_preprocessing=spec.requested_preprocessing,
        )
        band_statistics = image.reduceRegion(
            reducer=ee.Reducer.mean(), geometry=region, scale=scale, maxPixels=1_000_000_000,
            bestEffort=True,
        ).getInfo()

        comparison_band_statistics = None
        if spec.comparison_temporal_start is not None and spec.comparison_temporal_end is not None:
            comparison_image, _ = self._build_composite(
                source=source,
                region=region,
                declared_crs=spec.declared_crs,
                temporal_start=spec.comparison_temporal_start,
                temporal_end=spec.comparison_temporal_end,
                requested_preprocessing=spec.requested_preprocessing,
            )
            comparison_band_statistics = comparison_image.reduceRegion(
                reducer=ee.Reducer.mean(), geometry=region, scale=scale,
                maxPixels=1_000_000_000, bestEffort=True,
            ).getInfo()

        # Bug fix (post-RC1 Production Acceptance Test): band_statistics
        # above is already the real, authoritative output of a GEE fetch
        # (it's all Feature Extraction ever reads — extract_features() in
        # application/handlers.py takes band_statistics, never this raw
        # download's bytes) — proven by the fact that as of this fix,
        # nothing downstream in Analysis/Prediction/Validation/the
        # frontend has ever consumed a GEE job's raw raster content
        # (there is no raster pipeline anywhere in this platform; see
        # RasterMetadataResponse.available, always False). The raw pixel
        # download below is therefore best-effort only: Earth Engine's
        # synchronous getDownloadURL has a fixed, real request-size limit
        # (observed: 50331648 bytes) that any AOI larger than a small test
        # square exceeds at native resolution — that must not fail an
        # acquisition whose real, useful output was already computed
        # successfully above. Only this specific, identified Earth Engine
        # error is caught; anything else (including a failure in the
        # reduceRegion calls above, which run BEFORE this block and are
        # entirely unaffected by it) still propagates and fails the job,
        # via fetch()'s existing outer exception handler.
        raster_content: bytes | None = None
        raster_skipped_reason: str | None = None
        try:
            download_url = image.getDownloadURL(
                {"region": region, "scale": scale, "format": "GEO_TIFF"}
            )
            response = requests.get(download_url, timeout=120)
            response.raise_for_status()
            raster_content = response.content
            logger.debug(
                "GEE raster download for %s: Content-Type=%s, %d bytes",
                source.value,
                response.headers.get("Content-Type"),
                len(raster_content),
            )
            if raster_content[:4] not in _TIFF_MAGIC:
                # Diagnostic only — this platform's only consumer of this
                # content is validate_geotiff()'s own magic-byte check
                # (domain/validation.py), which will independently reject
                # it too. Logged here, at the one place that still has the
                # real HTTP response (Content-Type header, exact byte
                # prefix) available, since that context is gone by the
                # time validate_dataset_content() sees only raw bytes.
                logger.warning(
                    "GEE raster download for %s did not start with a TIFF header "
                    "(Content-Type=%s); first 32 bytes hex=%s printable=%r",
                    source.value,
                    response.headers.get("Content-Type"),
                    raster_content[:32].hex(),
                    "".join(
                        chr(b) if 32 <= b < 127 else "." for b in raster_content[:32]
                    ),
                )
        except (ee.EEException, requests.HTTPError) as exc:
            if not _is_request_size_limit_error(exc):
                raise
            raster_skipped_reason = (
                "Raster download skipped: exceeded Earth Engine's synchronous "
                f"request-size limit ({exc})"
            )
            logger.warning(
                "GEE raster download skipped for %s (request-size limit); "
                "continuing with band statistics only: %s",
                source.value,
                exc,
            )

        return FetchResult(
            success=True,
            content=raster_content,
            error=None,
            applied_preprocessing=tuple(applied),
            band_statistics=band_statistics,
            comparison_band_statistics=comparison_band_statistics,
            raster_skipped_reason=raster_skipped_reason,
        )

    def _build_composite(
        self,
        *,
        source: RemoteSensingSource,
        region: ee.Geometry,
        declared_crs: str,
        temporal_start: datetime | None,
        temporal_end: datetime | None,
        requested_preprocessing: tuple[PreprocessingStep, ...],
    ) -> tuple[ee.Image, list[PreprocessingStep]]:
        collection_id = _COLLECTION_BY_SOURCE[source]
        collection = ee.ImageCollection(collection_id).filterBounds(region)
        if temporal_start is not None and temporal_end is not None:
            collection = collection.filterDate(
                temporal_start.date().isoformat(), temporal_end.date().isoformat()
            )

        # Bug fix: CLOUD_MASKING must run per-image, via .map(), BEFORE
        # .median() composites the collection — not after, on the
        # already-composited single image (the original bug here).
        # ee.ImageCollection.median() is a per-band reducer that runs
        # across EVERY band, including QA60/QA_PIXEL, and Earth Engine's
        # median reducer always returns a FLOAT-typed band regardless of
        # the inputs' integer type (well-documented Earth Engine
        # behaviour, not specific to this codebase) — so calling
        # .bitwiseAnd() on that band afterward crashes with exactly
        # "Image.bitwiseAnd: Bitwise operands must be integer only."
        # Reproduced and confirmed via a live GEE call before this fix.
        # This is also not just a crash: masking a composite AFTER the
        # fact is semantically wrong regardless — the whole point of
        # cloud masking is to exclude cloud-contaminated pixels from
        # ever contributing to the median in the first place. Masking
        # each raw image (still genuinely integer-typed) before
        # compositing is both the fix and the only version of this that
        # was ever going to be correct.
        cloud_masking_applied: list[PreprocessingStep] = []
        if PreprocessingStep.CLOUD_MASKING in requested_preprocessing:
            if source == RemoteSensingSource.SENTINEL_2:
                collection = collection.map(_mask_sentinel2_clouds)
                cloud_masking_applied.append(PreprocessingStep.CLOUD_MASKING)
            elif source == RemoteSensingSource.LANDSAT:
                collection = collection.map(_mask_landsat_clouds)
                cloud_masking_applied.append(PreprocessingStep.CLOUD_MASKING)
            # else: no usable cloud/QA band for this source in this
            # pipeline — honestly not applied, not silently faked.

        image = collection.median()
        remaining_steps = tuple(
            step for step in requested_preprocessing if step != PreprocessingStep.CLOUD_MASKING
        )
        image, applied = _apply_preprocessing(
            image,
            source=source,
            region=region,
            declared_crs=declared_crs,
            requested_steps=remaining_steps,
        )
        return image, cloud_masking_applied + applied
