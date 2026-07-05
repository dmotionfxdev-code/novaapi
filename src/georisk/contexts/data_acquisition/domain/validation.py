"""Sprint 13 requirement #4 — "Dataset Validation: CRS validation,
Metadata validation, Geometry validation." Deliberately fresh, pure-
Python, no-heavy-dependency structural validators — NOT a reuse of
``contexts.geospatial``'s ``Geometry`` class, since the peer-independence
contract forbids Data Acquisition from importing another context's
internals, and a full GIS-library-backed validator (shapely/rasterio/
fiona) is exactly the "hazard-specific dependency lands with the sprint
that needs it" tradeoff this platform has deferred since Sprint 0 — these
functions validate *structure* (is this well-formed GeoJSON/CSV/GeoTIFF/
Shapefile/JSON, does it declare a usable CRS), not full geometric
correctness (self-intersection, ring winding, etc.), which is out of
scope for what Sprint 13 actually asked for.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass

from georisk.contexts.data_acquisition.domain.value_objects import AcquisitionFormat

_EPSG_PATTERN = re.compile(r"^EPSG:\d+$")

#: A valid top-level GeoJSON ``type`` (RFC 7946 §1.4).
_GEOJSON_TYPES = frozenset(
    {
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
        "Feature",
        "FeatureCollection",
    }
)

# TIFF magic bytes: little-endian ("II*\x00") or big-endian ("MM\x00*").
_TIFF_MAGIC = (b"II*\x00", b"MM\x00*")

# Shapefile (.shp) file code 9994, big-endian, per the ESRI Shapefile spec.
_SHAPEFILE_MAGIC = b"\x00\x00\x27\x0a"


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    is_valid: bool
    errors: tuple[str, ...]
    extracted_metadata: dict[str, object]


def validate_crs(crs: str) -> list[str]:
    """Requirement #4's "CRS validation" — accepts the ``EPSG:<code>``
    form ``DatasetMetadata.crs`` already uses throughout this context
    (e.g. ``"EPSG:4326"``); rejects blank or malformed values."""
    if not crs.strip():
        return ["CRS must not be blank"]
    if not _EPSG_PATTERN.match(crs.strip()):
        return [f"CRS {crs!r} is not of the form 'EPSG:<code>'"]
    return []


def validate_geojson(content: bytes) -> tuple[list[str], dict[str, object]]:
    """Requirement #4's "Geometry validation" for the GeoJSON format."""
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"Not valid JSON: {exc}"], {}
    if not isinstance(parsed, dict):
        return ["GeoJSON root must be a JSON object"], {}
    geojson_type = parsed.get("type")
    if geojson_type not in _GEOJSON_TYPES:
        return [f"Unrecognized GeoJSON type: {geojson_type!r}"], {}
    if geojson_type == "FeatureCollection":
        features = parsed.get("features")
        if not isinstance(features, list):
            return ["FeatureCollection.features must be a list"], {}
        return [], {"feature_count": len(features)}
    if geojson_type == "Feature":
        if "geometry" not in parsed:
            return ["Feature is missing a 'geometry' member"], {}
        return [], {"feature_count": 1}
    return [], {"feature_count": 1}


def validate_csv(content: bytes) -> tuple[list[str], dict[str, object]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"Not valid UTF-8 text: {exc}"], {}
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return ["CSV content is empty"], {}
    header, data_rows = rows[0], rows[1:]
    if not header:
        return ["CSV header row is empty"], {}
    return [], {"column_count": len(header), "row_count": len(data_rows)}


def validate_geotiff(content: bytes) -> tuple[list[str], dict[str, object]]:
    if len(content) < 8 or content[:4] not in _TIFF_MAGIC:
        return ["Content does not start with a valid TIFF header"], {}
    return [], {"byte_size": len(content)}


def validate_shapefile(content: bytes) -> tuple[list[str], dict[str, object]]:
    if len(content) < 100 or content[:4] != _SHAPEFILE_MAGIC:
        return ["Content does not start with a valid Shapefile (.shp) header"], {}
    return [], {"byte_size": len(content)}


def validate_json(content: bytes) -> tuple[list[str], dict[str, object]]:
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [f"Not valid JSON: {exc}"], {}
    return [], {"json_type": type(parsed).__name__}


_VALIDATORS_BY_FORMAT = {
    AcquisitionFormat.GEOJSON: validate_geojson,
    AcquisitionFormat.CSV: validate_csv,
    AcquisitionFormat.GEOTIFF: validate_geotiff,
    AcquisitionFormat.SHAPEFILE: validate_shapefile,
    AcquisitionFormat.JSON: validate_json,
}


def validate_dataset_content(
    *, format: AcquisitionFormat, content: bytes, crs: str
) -> ValidationOutcome:
    """The single entry point the Dataset Import Pipeline (Sprint 13
    requirement #3) calls: dispatches to the format-specific structural
    validator, then always additionally runs CRS validation regardless of
    format (requirement #4's "CRS validation" applies to every format,
    including tabular CSV — a dataset's declared coordinate system is
    metadata about the dataset, not something only vector formats carry).
    """
    format_errors, extracted_metadata = _VALIDATORS_BY_FORMAT[format](content)
    crs_errors = validate_crs(crs)
    errors = [*format_errors, *crs_errors]
    return ValidationOutcome(
        is_valid=not errors, errors=tuple(errors), extracted_metadata=extracted_metadata
    )
