"""Sprint 13 requirement #2 — the Provider Registry — plus the
``AcquisitionProvider`` Protocol every provider adapter implements and the
one adapter that needs no real I/O (``LocalUploadProvider``), placed here
rather than ``infrastructure/`` for the same reason Sprint 11's
``UnconfiguredSmsNotificationChannel``/``InAppNotificationChannel`` live
in ``notification/application/ports.py``. ``HttpAcquisitionProvider``
(USGS/NASA/Copernicus — real ``requests``-based HTTP) and, as of Sprint
14, the real ``GoogleEarthEngineProvider`` (genuine ``earthengine-api``
I/O — superseding Sprint 13's interface-only stub of the same name) both
live in ``infrastructure/`` instead, mirroring
``SmtpEmailNotificationChannel``'s placement.

Sprint 14 also adds ``RemoteSensingFetchSpec``/``AoiGeometryInfo``/
``AoiReader`` — the Remote Sensing Integration's read-only port into
Geospatial's ``AreaOfInterest`` (requirement #5, AOI-based Processing).
``AoiReader`` follows the exact "conformist downstream reader Protocol,
composition-root implementation" pattern every peer-context read in this
codebase already uses (Reporting/Notification/Validation/Dashboard) —
Data Acquisition's first cross-context read, Sprint 13 never having
needed one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from georisk.contexts.data_acquisition.domain.errors import NoProviderRegisteredError
from georisk.contexts.data_acquisition.domain.value_objects import (
    DataProvider,
    PreprocessingStep,
    RemoteSensingSource,
)
from georisk.contexts.identity.domain.value_objects import TenantId


@dataclass(frozen=True, slots=True)
class RemoteSensingFetchSpec:
    """Everything a remote-sensing-aware provider (only
    ``GoogleEarthEngineProvider`` reads this; ``LocalUploadProvider``/
    ``HttpAcquisitionProvider`` ignore it) needs beyond the plain
    ``source_reference``/``raw_content`` Sprint 13 already threads
    through. ``aoi_geometry`` is a plain GeoJSON ``dict`` — never a typed
    Geospatial ID/entity — resolved by the handler via ``AoiReader``
    BEFORE calling ``fetch()``, so no provider ever imports
    ``contexts.geospatial`` (peer-independence)."""

    remote_sensing_source: RemoteSensingSource | None
    declared_crs: str
    temporal_start: datetime | None
    temporal_end: datetime | None
    comparison_temporal_start: datetime | None
    comparison_temporal_end: datetime | None
    aoi_geometry: dict | None
    requested_preprocessing: tuple[PreprocessingStep, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class FetchResult:
    success: bool
    content: bytes | None
    error: str | None
    applied_preprocessing: tuple[PreprocessingStep, ...] = field(default_factory=tuple)
    band_statistics: dict[str, float] | None = None
    comparison_band_statistics: dict[str, float] | None = None


class AcquisitionProvider(Protocol):
    async def fetch(
        self,
        *,
        source_reference: str,
        raw_content: bytes | None = None,
        spec: RemoteSensingFetchSpec | None = None,
    ) -> FetchResult: ...


class LocalUploadProvider:
    """The one provider that is genuinely fully real without any network
    I/O: the "fetch" is simply handing back the bytes the caller already
    uploaded (``raw_content``, threaded through from
    ``AcquisitionJob.raw_content_base64`` by the pipeline handler). Never
    reads ``spec`` — Local Upload has no remote collection to query."""

    async def fetch(
        self,
        *,
        source_reference: str,
        raw_content: bytes | None = None,
        spec: RemoteSensingFetchSpec | None = None,
    ) -> FetchResult:
        if raw_content is None:
            return FetchResult(
                success=False, content=None, error="No file content provided for local upload"
            )
        return FetchResult(success=True, content=raw_content, error=None)


@dataclass(frozen=True, slots=True)
class AoiGeometryInfo:
    aoi_id: str
    geometry: dict


class AoiReader(Protocol):
    async def get_aoi_geometry(
        self, *, tenant_id: TenantId, aoi_id: str
    ) -> AoiGeometryInfo | None: ...


class ProviderRegistry:
    """"the single lookup every [acquisition pipeline] command handler
    calls" — mirrors ``contexts.analysis``'s ``StrategyRegistry`` exactly:
    new providers register with this lookup at platform startup; callers
    never change to accommodate a new registrant."""

    def __init__(self) -> None:
        self._providers: dict[DataProvider, AcquisitionProvider] = {}

    def register(self, provider: DataProvider, adapter: AcquisitionProvider) -> None:
        self._providers[provider] = adapter

    def resolve(self, provider: DataProvider) -> AcquisitionProvider:
        adapter = self._providers.get(provider)
        if adapter is None:
            raise NoProviderRegisteredError(f"No AcquisitionProvider registered for {provider}")
        return adapter
