"""Value objects for the Geospatial context (Domain Model §1 rows 3-4:
``AreaOfInterest``'s ``Geometry``/``AoiMetadata``, ``SamplingCampaign``'s
``SamplingStrategy``).

Sprint 7 scope note: ``Geometry`` stores validated GeoJSON in a plain
JSONB column, not a native PostGIS geometry column. The Infrastructure
Architecture document's approved design (§3) calls for
``geometry(MultiPolygon, 4326)`` with GiST indexing — that remains the
target, but no PostGIS installation is available in this platform's
validation environment (embedded ``pgserver`` Postgres, no extension
support) or, as far as this sprint could verify, anywhere else in this
environment. Shipping code that can only be "assumed correct" against
infrastructure that cannot actually be exercised contradicts this
project's own validation discipline (every sprint validates against real
Postgres). JSONB + pure-Python geometry math (``geometry.py``) is fully
testable today; upgrading to native PostGIS columns, GiST indexes, and
``ST_Intersects``-backed spatial search is deferred to whenever the
platform actually needs spatial SQL queries — a follow-on infrastructure
task, not a blocker for the AOI/Sampling domain logic this sprint builds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from georisk.shared_kernel.ids import TypedId


class AoiId(TypedId):
    pass


class SamplingCampaignId(TypedId):
    pass


class SamplePointId(TypedId):
    pass


class AoiSource(StrEnum):
    """How the AOI's geometry was supplied (Domain Model §3's
    ``AoiMetadata.source``) — mirrors the legacy ``AOI.source`` choices."""

    DRAWN = "DRAWN"
    GEOJSON_UPLOAD = "GEOJSON_UPLOAD"
    KML_UPLOAD = "KML_UPLOAD"
    SHAPEFILE = "SHAPEFILE"
    RECTANGLE = "RECTANGLE"
    SEARCH = "SEARCH"


class AoiStatus(StrEnum):
    """"One AOI is ACTIVE per assessment at a time; edits create a new
    version, never mutate in place" (Domain Model §1 row 3). Revising an
    assessment's AOI supersedes the previous version — both rows persist,
    only one is ever ``ACTIVE``."""

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


GEOJSON_GEOMETRY_TYPES = frozenset({"Polygon", "MultiPolygon"})


@dataclass(frozen=True, slots=True)
class Geometry:
    """A validated GeoJSON Polygon/MultiPolygon, always stored in
    EPSG:4326 (Infrastructure Architecture §3's "SRID discipline: EPSG:4326
    for storage" — the one part of that discipline achievable without a
    native PostGIS column). Validity is checked structurally on
    construction (ring closure, coordinate shape) — the closest
    JSONB-only equivalent to ``ST_IsValid``.
    """

    geojson: dict
    srid: int = 4326

    def __post_init__(self) -> None:
        geometry_type = self.geojson.get("type")
        if geometry_type not in GEOJSON_GEOMETRY_TYPES:
            raise ValueError(
                f"Geometry.geojson['type'] must be one of {sorted(GEOJSON_GEOMETRY_TYPES)}, "
                f"got {geometry_type!r}"
            )
        coordinates = self.geojson.get("coordinates")
        if not coordinates:
            raise ValueError("Geometry.geojson['coordinates'] must be non-empty")
        for ring in self._rings(geometry_type, coordinates):
            if len(ring) < 4:
                raise ValueError(
                    "Geometry ring must have at least 4 positions (closed triangle), "
                    f"got {len(ring)}"
                )
            if tuple(ring[0]) != tuple(ring[-1]):
                raise ValueError("Geometry ring must be closed (first position == last position)")

    @staticmethod
    def _rings(geometry_type: str, coordinates: list) -> list[list]:
        if geometry_type == "Polygon":
            return list(coordinates)
        # MultiPolygon: list[Polygon] where Polygon = list[ring]
        rings = []
        for polygon in coordinates:
            rings.extend(polygon)
        return rings

    def exterior_rings(self) -> list[list[tuple[float, float]]]:
        """Every polygon's *exterior* ring (index 0) as a flat list —
        interior rings (holes) are ignored for area/centroid/sampling
        purposes, matching the legacy ``geometry.py``'s scope."""
        geometry_type = self.geojson["type"]
        coordinates = self.geojson["coordinates"]
        if geometry_type == "Polygon":
            return [coordinates[0]]
        return [polygon[0] for polygon in coordinates]


@dataclass(frozen=True, slots=True)
class BoundingBox:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


@dataclass(frozen=True, slots=True)
class Centroid:
    longitude: float
    latitude: float


@dataclass(frozen=True, slots=True)
class AoiMetadata:
    name: str
    source: AoiSource
    notes: str = ""


class SamplingMethod(StrEnum):
    STRATIFIED_RANDOM = "STRATIFIED_RANDOM"
    SIMPLE_RANDOM = "SIMPLE_RANDOM"


class AllocationMethod(StrEnum):
    PROPORTIONAL = "PROPORTIONAL"
    EQUAL = "EQUAL"


class OutputFormat(StrEnum):
    GEOJSON = "GEOJSON"
    CSV = "CSV"
    SHAPEFILE = "SHAPEFILE"


class SamplingCampaignStatus(StrEnum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"


# GEORISK_SCOPE_REALIGNMENT.md §4 — binding, platform-wide (confirmed
# inherited unchanged by WRRAS, WRRAS_ARCHITECTURE_ALIGNMENT.md §9): note
# the approved max (5,000) is a deliberate downward revision from the
# legacy `SamplingConfig.max_sample_size` default (50,000) — not a
# straight port.
MIN_SAMPLE_SIZE = 1_000
MAX_SAMPLE_SIZE = 5_000
DEFAULT_SAMPLE_SIZE = 5_000
MIN_PER_CLASS = 30


@dataclass(frozen=True, slots=True)
class Stratum:
    """A named sub-population within the AOI and its target share of the
    total sample. Sprint 7 scope note: without real land-cover raster
    data (Geospatial has no GEE integration yet), strata are user-declared
    proportions, not raster-derived classes — see ``sampling.py``'s
    module docstring."""

    label: str
    proportion: float

    def __post_init__(self) -> None:
        if not (0.0 < self.proportion <= 1.0):
            raise ValueError(f"Stratum proportion must be in (0, 1], got {self.proportion}")


@dataclass(frozen=True, slots=True)
class SamplingStrategy:
    """Domain Model §1 row 4's ``SamplingStrategy`` VO — the approved
    binding defaults from ``GEORISK_SCOPE_REALIGNMENT.md`` §4, expressed
    as this VO's field defaults."""

    method: SamplingMethod = SamplingMethod.STRATIFIED_RANDOM
    sample_size: int = DEFAULT_SAMPLE_SIZE
    min_per_class: int = MIN_PER_CLASS
    allocation_method: AllocationMethod = AllocationMethod.PROPORTIONAL
    random_seed: int = 12345
    coordinate_system: str = "EPSG:4326"
    output_formats: frozenset[OutputFormat] = field(
        default_factory=lambda: frozenset({OutputFormat.GEOJSON, OutputFormat.CSV})
    )
    include_geometry: bool = True
    include_class_label: bool = True
    include_pixel_values: bool = False

    def __post_init__(self) -> None:
        if not (MIN_SAMPLE_SIZE <= self.sample_size <= MAX_SAMPLE_SIZE):
            raise ValueError(
                f"sample_size must be between {MIN_SAMPLE_SIZE} and {MAX_SAMPLE_SIZE}, "
                f"got {self.sample_size}"
            )
        if not self.output_formats:
            raise ValueError("output_formats must include at least one format")


@dataclass(frozen=True, slots=True)
class SamplePoint:
    """Domain Model §2's ``SamplePoint`` entity — "coordinate + stratum
    label; generated deterministically from the campaign's
    ``SamplingStrategy``." Modeled as a frozen VO-shaped record (with its
    own identity, per the domain model calling it an entity) since it is
    never independently persisted/queried outside its parent
    ``SamplingCampaign``.
    """

    id: SamplePointId
    longitude: float
    latitude: float
    stratum: str | None = None
