"""Sprint B — real ESRI Shapefile ingestion. The ONLY module in this
platform allowed to import ``pyogrio``/``shapely`` (import-linter's
"External GIS/GEE libraries only imported behind data_acquisition's
infrastructure layer" contract, extended this sprint to also forbid these
two packages outside this file, mirroring ``gee_connector.py``'s exact
precedent for ``ee``).

Supersedes ``domain/validation.py``'s original ``validate_shapefile`` —
that function checked only the ``.shp`` file-code magic bytes (a single
4-byte header check that, as this sprint's own investigation confirmed,
GDAL's own Shapefile driver doesn't even use to decide whether a file is
readable). This module genuinely parses: real geometries (via
``pyogrio.raw.read``'s per-feature WKB), real attributes (the same call's
field data), the actual per-feature geometry type (via ``shapely.wkb``,
not just the Shapefile header's shape-type code — empirically, a
disjoint-multi-ring feature written as ESRI shape type 5 ["Polygon"]
genuinely decodes to WKB type MultiPolygon; the Shapefile FORMAT has no
separate "MultiPolygon" shape-type code, so relying on the header alone
would misreport every true MultiPolygon as "Polygon"), the real CRS (via
``pyogrio.read_info``'s CRS resolution, which parses the ``.prj``
WKT — never assumed from ``declared_crs``), and the real bounding box
(GDAL's own ``total_bounds``, not hand-computed from geometries — GDAL's
own fast-path for this is exactly what a mature library is for).

**Library choice**: ``pyogrio`` (GDAL/OGR bindings) + ``shapely`` (GEOS
bindings for per-feature WKB geometry-type inspection), not Fiona or
"osgeo.ogr" directly. Justification: (1) both ship self-contained
manylinux wheels bundling their own GDAL/GEOS build — no system
``libgdal``/``gdal-config`` needed, which matters for this platform's
shared-hosting cPanel deployment target (the same "minimal system
dependencies" reasoning Sprint 0 already applied to embedded-Postgres
validation); a bare ``osgeo.ogr`` install is notoriously fragile outside
a matching system GDAL. (2) ``pyogrio`` is the actively-developed,
faster successor the GeoPandas project itself now recommends over Fiona
(vectorized reads via the OGR C API, avoiding Fiona's per-feature Python
object overhead) — Fiona remains usable but is the legacy choice for new
code as of this sprint. (3) Both accept an in-memory ``BytesIO`` of a ZIP
archive directly (verified: ``pyogrio.read_info(io.BytesIO(zip_bytes))``
transparently uses GDAL's ``/vsizip/`` virtual filesystem) — no temporary
files, no cleanup/collision risk for a multi-tenant web service.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pyogrio
import shapely.geometry
import shapely.wkb

from georisk.contexts.data_acquisition.domain.errors import (
    CorruptedShapefileError,
    EmptyShapefileDatasetError,
    InvalidShapefileCrsError,
    UnsupportedShapefileGeometryError,
)
from georisk.contexts.data_acquisition.domain.validation import validate_crs

#: Bumped whenever this module's parsing/validation logic changes in a way
#: that could affect a previously-imported dataset's recorded provenance —
#: recorded on every successful import (Sprint B requirement #5).
SHAPEFILE_IMPORTER_VERSION = "pyogrio-shapefile-importer-v1"

#: The geometry types this platform supports for a Shapefile-sourced
#: Dataset — RFC 7946's vocabulary (matching ``domain/validation.py``'s
#: own ``_GEOJSON_TYPES`` for the same concepts), minus the two
#: container-level GeoJSON-only members (``Feature``/``FeatureCollection``)
#: and ``GeometryCollection`` (a Shapefile can never legally contain one —
#: if GDAL ever reports it, that means genuinely mixed per-feature
#: geometry types, handled as the same "unsupported" case below).
_SUPPORTED_GEOMETRY_TYPES = frozenset(
    {"Point", "MultiPoint", "LineString", "MultiLineString", "Polygon", "MultiPolygon"}
)


@dataclass(frozen=True, slots=True)
class ShapefileImportResult:
    """Everything Sprint B requirement #3 asks the importer to genuinely
    read/compute from a Shapefile archive, plus the first feature's real
    attribute row (used by ``CompositionRootIndicatorInputProvider``,
    Sprint A, requirement #8, to feed Analysis)."""

    geometry_type: str
    feature_count: int
    bounding_box: tuple[float, float, float, float]
    crs: str
    field_names: tuple[str, ...]
    first_feature_attributes: dict[str, object]


@dataclass(frozen=True, slots=True)
class ShapefileFeature:
    """One genuine feature's geometry (GeoJSON-shaped, via
    ``shapely.geometry.mapping`` — RFC 7946 compliant, directly usable in
    a ``FeatureCollection``) and its real DBF attribute row. Sprint C's
    Risk Layer Generator pairs these with a completed Analysis
    ``StageResult`` to build genuine spatial outputs — never fabricated,
    since every one of these comes from ``read_all_features`` actually
    decoding the uploaded archive's own per-feature WKB.
    """

    geometry: dict
    properties: dict[str, object]


def _to_plain_python(value: object) -> object:
    """numpy scalars (``numpy.float64``/``numpy.int64``/...) aren't JSON
    serializable as-is — pyogrio's field arrays are numpy dtypes even for
    a single extracted value; ``.item()`` converts a numpy scalar to its
    plain Python equivalent. Already-plain values (Python ``str``) pass
    through ``.item``-free, since they don't have that method."""
    return value.item() if hasattr(value, "item") else value


def parse_shapefile_archive(content: bytes) -> ShapefileImportResult:
    """The Dataset Import Pipeline's real Shapefile parse step — called
    from ``ExecuteAcquisitionJobHandler`` (application layer) only AFTER
    ``domain.validation.validate_shapefile_archive`` has already confirmed
    the ZIP is structurally complete (has exactly one ``.shp`` plus its
    ``.shx``/``.dbf``/``.prj`` companions). Raises a specific domain error
    for every genuine failure mode Sprint B requirement #6 names; never
    lets a raw ``pyogrio``/GDAL exception (which, as this sprint's own
    testing found, can be an untyped ``IndexError`` for a wholesale-
    corrupted ``.shp``, not always one of ``pyogrio.errors``'s own typed
    exceptions) escape this module.
    """
    try:
        info = pyogrio.read_info(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 — GDAL's own failure modes for
        # a genuinely corrupted archive are not reliably one of
        # ``pyogrio.errors``'s typed exceptions (empirically confirmed: a
        # severely truncated .shp raises a bare ``IndexError`` from
        # pyogrio's own internal numpy indexing, not a GDAL-specific
        # error type) — this is exactly the "isolate an untrusted
        # boundary" pattern every provider-adapter call site in this
        # codebase already applies (e.g. ``ExecuteAcquisitionJobHandler``
        # around ``provider_adapter.fetch()``).
        raise CorruptedShapefileError(
            f"Could not parse Shapefile archive: {exc}"
        ) from exc

    feature_count = int(info["features"])
    if feature_count == 0:
        raise EmptyShapefileDatasetError(
            "Shapefile archive parses cleanly but contains zero features"
        )

    crs = info["crs"]
    if not crs:
        raise InvalidShapefileCrsError(
            "Could not resolve a coordinate reference system from the .prj component "
            "(missing, empty, or GDAL could not parse its WKT)"
        )
    crs_errors = validate_crs(crs)
    if crs_errors:
        raise InvalidShapefileCrsError(
            f"Shapefile CRS {crs!r} resolved but is not supported: {'; '.join(crs_errors)}"
        )

    try:
        _meta, _fid, geometries, field_data = pyogrio.raw.read(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 — same untrusted-boundary reasoning as above.
        raise CorruptedShapefileError(
            f"Could not read Shapefile geometries/attributes: {exc}"
        ) from exc

    # The Shapefile FORMAT has no distinct "MultiPolygon"/"MultiLineString"
    # shape-type code — ``info["geometry_type"]`` (from the header alone)
    # under-reports a disjoint-multi-ring feature as plain "Polygon".
    # Reading each feature's ACTUAL WKB type via shapely is the only
    # genuinely correct way to detect a true Multi* dataset.
    geom_types = {shapely.wkb.loads(wkb).geom_type for wkb in geometries}
    if len(geom_types) > 1:
        raise UnsupportedShapefileGeometryError(
            f"Shapefile features disagree on geometry type: {sorted(geom_types)}"
        )
    geometry_type = next(iter(geom_types))
    if geometry_type not in _SUPPORTED_GEOMETRY_TYPES:
        raise UnsupportedShapefileGeometryError(
            f"Geometry type {geometry_type!r} is not supported "
            f"(supported: {sorted(_SUPPORTED_GEOMETRY_TYPES)})"
        )

    field_names = tuple(str(name) for name in info["fields"])
    first_feature_attributes = {
        field_name: _to_plain_python(field_data[i][0]) for i, field_name in enumerate(field_names)
    }

    xmin, ymin, xmax, ymax = (float(v) for v in info["total_bounds"])
    return ShapefileImportResult(
        geometry_type=geometry_type,
        feature_count=feature_count,
        bounding_box=(xmin, ymin, xmax, ymax),
        crs=crs,
        field_names=field_names,
        first_feature_attributes=first_feature_attributes,
    )


def read_all_features(content: bytes) -> list[ShapefileFeature]:
    """Sprint C: reads EVERY feature's real geometry (converted to a
    GeoJSON-shaped dict via ``shapely.geometry.mapping``) and real
    attributes — unlike ``parse_shapefile_archive``'s
    ``first_feature_attributes`` (Sprint B), which only ever needed one
    representative row to feed ``CompositionRootIndicatorInputProvider``.
    The Risk Layer Generator (composition root, ``api/risk_layer_ports
    .py``) calls this to build a genuine ``FeatureCollection`` from the
    SAME uploaded archive Sprint B already validated as complete and
    parseable — every returned feature corresponds to one real uploaded
    feature; none are fabricated.
    """
    try:
        info = pyogrio.read_info(io.BytesIO(content))
        _meta, _fid, geometries, field_data = pyogrio.raw.read(io.BytesIO(content))
    except Exception as exc:  # noqa: BLE001 — same untrusted-boundary
        # reasoning as ``parse_shapefile_archive`` above: GDAL's own
        # failure modes for a genuinely corrupted archive are not
        # reliably one of ``pyogrio.errors``'s typed exceptions.
        raise CorruptedShapefileError(
            f"Could not read Shapefile geometries/attributes: {exc}"
        ) from exc

    field_names = [str(name) for name in info["fields"]]
    features: list[ShapefileFeature] = []
    for i, wkb in enumerate(geometries):
        geometry = dict(shapely.geometry.mapping(shapely.wkb.loads(wkb)))
        properties = {
            name: _to_plain_python(field_data[j][i]) for j, name in enumerate(field_names)
        }
        features.append(ShapefileFeature(geometry=geometry, properties=properties))
    return features
