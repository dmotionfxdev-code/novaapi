"""Value objects for the Data Acquisition context (Domain Model §1 rows
5/9: ``DatasetSource``'s ``ProviderConfig``, ``UserVariable``'s
``VariableDefinition``) — extended this sprint with the explicit
``DatasetMetadata``/``ProvenanceEntry`` shape Sprint 7's brief requires
(Dataset Catalog, Metadata Framework, Provenance Tracking), which the
original architecture docs left unspecified (see
``WRRAS_ARCHITECTURE_ALIGNMENT.md``-style research: neither concept is
named in ``FIRAS_V2_DOMAIN_MODEL.md`` — designed fresh here, informed by
the legacy ``apps/variables/models.py`` ``DatasetSource`` fields).

Sprint 7 scope note: this is the *catalog/registry* half of Data
Acquisition — metadata about datasets, not the datasets' actual raster/
vector/tabular payloads. No GEE integration, no actual data fetching;
``AcquisitionJob``/``SensorStation``/``SensorReading`` (the "go fetch real
data" aggregates) remain out of scope, exactly as instructed ("No GEE
integration yet").

Sprint 13 extends this same file with the "go fetch real data" half:
``AcquisitionJobId``/``AcquisitionFormat``/``AcquisitionJobStatus`` for
the new ``AcquisitionJob`` aggregate (``entities.py``), plus five new
``DataProvider`` members (``GOOGLE_EARTH_ENGINE``, ``USGS``, ``NASA``,
``COPERNICUS``, ``LOCAL_UPLOAD``) — additive to the existing enum rather
than a parallel vocabulary, since a ``Dataset`` catalogued from a
completed ``AcquisitionJob`` reuses this exact same ``DataProvider``
field on its ``DatasetMetadata``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from georisk.shared_kernel.ids import TypedId
from georisk.shared_kernel.types import DateRange


class DatasetSourceId(TypedId):
    pass


class DatasetId(TypedId):
    pass


class PredictorVariableId(TypedId):
    pass


class VariableSelectionId(TypedId):
    pass


class AcquisitionJobId(TypedId):
    pass


class DataProvider(StrEnum):
    """Mirrors the legacy ``DatasetSource.provider`` choices
    (``apps/variables/models.py``) plus a few generic catch-alls this
    platform's registry needs that the legacy single-tenant system didn't
    (``USER_UPLOAD``, ``SENSOR``, ``MANUAL``, ``OTHER``).

    Sprint 13 adds the five *acquisition-provider*-level members Data
    Acquisition's "Support Providers" requirement names
    (``GOOGLE_EARTH_ENGINE``, ``USGS``, ``NASA``, ``COPERNICUS``,
    ``LOCAL_UPLOAD``) directly to this same enum rather than inventing a
    parallel vocabulary — a catalogued ``Dataset``'s ``DatasetMetadata.
    provider`` field is exactly this enum, and a ``Dataset`` produced by
    an ``AcquisitionJob`` needs to record which of these five fetched it.
    ``AcquisitionJob.schedule()`` restricts ``provider`` to just these
    five (Domain Model: an acquisition job is a *fetch*, not a citation of
    a product like CHIRPS/MODIS that some other, already-catalogued
    dataset happens to originate from)."""

    CHIRPS = "CHIRPS"
    ERA5 = "ERA5"
    MODIS = "MODIS"
    SENTINEL = "SENTINEL"
    LANDSAT = "LANDSAT"
    SMAP = "SMAP"
    VIIRS = "VIIRS"
    GRACE = "GRACE"
    GPM = "GPM"
    ERA5_LAND = "ERA5_LAND"
    MERRA2 = "MERRA2"
    NCEP = "NCEP"
    CRU = "CRU"
    WORLDCLIM = "WORLDCLIM"
    USER_UPLOAD = "USER_UPLOAD"
    SENSOR = "SENSOR"
    MANUAL = "MANUAL"
    OTHER = "OTHER"
    GOOGLE_EARTH_ENGINE = "GOOGLE_EARTH_ENGINE"
    USGS = "USGS"
    NASA = "NASA"
    COPERNICUS = "COPERNICUS"
    LOCAL_UPLOAD = "LOCAL_UPLOAD"


#: The subset of :class:`DataProvider` an ``AcquisitionJob`` may be
#: scheduled against — Sprint 13's five "Support Providers", not the
#: broader product-level vocabulary above (which describes what a
#: *catalogued* ``Dataset`` came from, once fetched).
ACQUISITION_CAPABLE_PROVIDERS: frozenset[DataProvider] = frozenset(
    {
        DataProvider.GOOGLE_EARTH_ENGINE,
        DataProvider.USGS,
        DataProvider.NASA,
        DataProvider.COPERNICUS,
        DataProvider.LOCAL_UPLOAD,
    }
)


class AcquisitionFormat(StrEnum):
    """Sprint 13's "Support Formats" list."""

    GEOJSON = "GEOJSON"
    CSV = "CSV"
    GEOTIFF = "GEOTIFF"
    SHAPEFILE = "SHAPEFILE"
    JSON = "JSON"


class AcquisitionJobStatus(StrEnum):
    """``AcquisitionJob``'s lifecycle — mirrors the ``Report`` DRAFT ->
    FINALIZED two-step pattern (Sprint 9) generalized to four states:
    SCHEDULED (durably persisted, not yet executed) -> RUNNING (durably
    persisted BEFORE the fetch/validate/catalog pipeline begins, so a
    crash mid-pipeline leaves an observable, non-silent RUNNING row rather
    than nothing) -> exactly one of COMPLETED/FAILED."""

    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RemoteSensingSource(StrEnum):
    """Sprint 14's "Supported Sources" — which real Earth Engine
    collection an ``AcquisitionJob`` pulls from when
    ``provider == DataProvider.GOOGLE_EARTH_ENGINE``. Deliberately a
    SEPARATE enum from ``DataProvider``: ``DataProvider`` answers "how is
    this fetched" (GEE/USGS/NASA/Copernicus/Local Upload — Sprint 13),
    this answers "which dataset/collection, once GEE is the answer to
    that" — a GEE job could in principle pull any of these six sources,
    so collapsing the two into one field would conflate two independent
    axes. The actual GEE collection ID and band layout for each member is
    resolved in ``infrastructure/gee_connector.py`` (kept out of the
    domain layer since it's third-party-catalog knowledge, not a domain
    rule)."""

    SENTINEL_1 = "SENTINEL_1"
    SENTINEL_2 = "SENTINEL_2"
    LANDSAT = "LANDSAT"
    MODIS = "MODIS"
    CHIRPS = "CHIRPS"
    ERA5 = "ERA5"


class PreprocessingStep(StrEnum):
    """Sprint 14's "Preprocessing" list — requested on
    ``AcquisitionJob.schedule()``, and echoed back (possibly narrower, if
    a step doesn't apply to the job's source — e.g. cloud masking has no
    meaning for CHIRPS/ERA5) as ``applied_preprocessing`` on completion."""

    CLOUD_MASKING = "CLOUD_MASKING"
    ATMOSPHERIC_CORRECTION = "ATMOSPHERIC_CORRECTION"
    RADIOMETRIC_CORRECTION = "RADIOMETRIC_CORRECTION"
    REPROJECTION = "REPROJECTION"
    AOI_CLIPPING = "AOI_CLIPPING"


class SpectralIndex(StrEnum):
    """Sprint 14's "Feature Extraction" list. Not every index applies to
    every source (e.g. LST needs a thermal band, SPEI needs both
    precipitation and temperature) — see
    ``domain/feature_extraction.py``'s ``extract_features`` for exactly
    which (source, index) pairs are computable versus honestly skipped
    with a reason."""

    NDVI = "NDVI"
    EVI = "EVI"
    SAVI = "SAVI"
    NDWI = "NDWI"
    LST = "LST"
    NBR = "NBR"
    DNBR = "DNBR"
    SPEI = "SPEI"


class DatasetType(StrEnum):
    RASTER = "RASTER"
    VECTOR = "VECTOR"
    TABULAR = "TABULAR"
    TIME_SERIES = "TIME_SERIES"
    POINT_OBSERVATIONS = "POINT_OBSERVATIONS"


class TemporalResolution(StrEnum):
    SUB_DAILY = "SUB_DAILY"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    DEKADAL = "DEKADAL"
    MONTHLY = "MONTHLY"
    SEASONAL = "SEASONAL"
    ANNUAL = "ANNUAL"
    STATIC = "STATIC"


class ProcessingMethod(StrEnum):
    """"Processing Method" — one of Sprint 7's required metadata fields.
    ``RAW`` is the honest default while no acquisition/processing
    pipeline exists yet (No GEE integration this sprint)."""

    RAW = "RAW"
    CLOUD_MASKED = "CLOUD_MASKED"
    COMPOSITED = "COMPOSITED"
    DERIVED_INDEX = "DERIVED_INDEX"
    AGGREGATED = "AGGREGATED"
    OTHER = "OTHER"


class DatasetStatus(StrEnum):
    """"Dataset Versioning" (Sprint 7 requirement #5) — same immutable,
    write-once-per-version pattern ``StageResult``/``AreaOfInterest``
    already established: a revision creates a new ``CATALOGUED`` row and
    flips the previous version to ``SUPERSEDED``, never mutates in
    place."""

    CATALOGUED = "CATALOGUED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class DatasetReadinessTag(StrEnum):
    """"Support: MLR-ready datasets / Correlation-Analysis-ready
    datasets" (Sprint 7). Deliberately *asserted* by whoever catalogues
    the dataset, not derived by a heuristic — this platform has no
    Prediction context yet to define what "ready" actually validates
    against; inventing scoring rules nobody asked for would be
    speculative. A future Prediction Engine sprint is the right place to
    decide what automated readiness validation should check."""

    MLR_READY = "MLR_READY"
    CORRELATION_READY = "CORRELATION_READY"


@dataclass(frozen=True, slots=True)
class DatasetMetadata:
    """Sprint 7's required metadata field list, verbatim:
    Dataset Name, Dataset Type, Dataset Source, Provider, Acquisition
    Date, Resolution, CRS, Spatial Coverage, Temporal Coverage,
    Processing Method, Model Used. ("Version" is the owning ``Dataset``
    aggregate's own field, matching ``StageResult.version``'s precedent
    of living on the aggregate rather than duplicated into an embedded
    VO.)
    """

    name: str
    dataset_type: DatasetType
    source: str
    provider: DataProvider
    acquisition_date: date
    spatial_resolution_m: float | None
    temporal_resolution: TemporalResolution | None
    crs: str
    spatial_coverage: str
    temporal_coverage: DateRange
    processing_method: ProcessingMethod
    model_used: str | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("DatasetMetadata.name must not be blank")
        if not self.crs.strip():
            raise ValueError("DatasetMetadata.crs must not be blank")


@dataclass(frozen=True, slots=True)
class ProvenanceEntry:
    """"Dataset Provenance Tracking" (Sprint 7 requirement #3) — an
    append-only lineage record. ``source_reference`` names what this
    entry was derived from (a previous ``DatasetId``, an external URL,
    or ``None`` for the original cataloguing entry)."""

    timestamp: datetime
    actor: str
    action: str
    description: str
    source_reference: str | None = None

    @classmethod
    def now(
        cls, *, actor: str, action: str, description: str, source_reference: str | None = None
    ) -> ProvenanceEntry:
        return cls(
            timestamp=datetime.now(UTC),
            actor=actor,
            action=action,
            description=description,
            source_reference=source_reference,
        )


class VariableCategory(StrEnum):
    """Generalizes the category headers every hazard's MLR variable list
    already uses (confirmed directly against both ``old-system/apps/firas
    /mlr.py``-equivalent and ``apps/wrras/mlr.py``'s ``CATEGORIES``:
    Vegetation & Fuel, Surface Energy, Meteorological, Terrain, Soil
    Moisture, Human Influence, Drought) — hazard-agnostic, so a future
    hazard's MLR variable set reuses this same registry rather than
    inventing its own categories."""

    VEGETATION_AND_FUEL = "VEGETATION_AND_FUEL"
    SURFACE_ENERGY = "SURFACE_ENERGY"
    METEOROLOGICAL = "METEOROLOGICAL"
    TERRAIN = "TERRAIN"
    SOIL_MOISTURE = "SOIL_MOISTURE"
    HUMAN_INFLUENCE = "HUMAN_INFLUENCE"
    DROUGHT = "DROUGHT"
    OTHER = "OTHER"


class VariableRole(StrEnum):
    """Mirrors the legacy ``UserVariable.variable_type`` choices — Domain
    Model §1 row 9's ``VariableDefinition`` names this same
    dependent/independent/derived/control split."""

    DEPENDENT = "DEPENDENT"
    INDEPENDENT = "INDEPENDENT"
    DERIVED = "DERIVED"
    CONTROL = "CONTROL"


class VariableDataType(StrEnum):
    CONTINUOUS = "CONTINUOUS"
    CATEGORICAL = "CATEGORICAL"
    BINARY = "BINARY"
    ORDINAL = "ORDINAL"


class VariableSelectionStatus(StrEnum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
