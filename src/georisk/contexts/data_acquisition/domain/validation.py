"""Sprint 13 requirement #4 — "Dataset Validation: CRS validation,
Metadata validation, Geometry validation." Deliberately fresh, pure-
Python, no-heavy-dependency structural validators — NOT a reuse of
``contexts.geospatial``'s ``Geometry`` class, since the peer-independence
contract forbids Data Acquisition from importing another context's
internals. These functions validate *structure* (is this well-formed
GeoJSON/CSV/GeoTIFF/JSON, does it declare a usable CRS), not full
geometric correctness — genuine GIS-library-backed parsing lives in
``infrastructure/shapefile_importer.py`` instead (Sprint B), since the
domain layer may never import a third-party GIS library (import-linter's
"External GIS/GEE libraries only imported behind data_acquisition's
infrastructure layer" contract) — the same reason
``infrastructure/gee_connector.py`` exists as a separate module rather
than living here.

Sprint B replaced ``validate_shapefile``'s original magic-byte-only check
(``content[:4] == b"\\x00\\x00\\x27\\x0a"``) with
``validate_shapefile_archive`` below: a genuine ZIP-completeness check
(is this a valid ZIP, does it contain exactly one ``.shp`` plus its
required ``.shx``/``.dbf``/``.prj`` companions) using only the stdlib
``zipfile`` module — still pure domain logic, no GIS library needed for
*this* check, since completeness is a question about file *names*, not
content. The actual geometry/attribute/CRS parsing this ZIP's contents
undergo happens afterward, in the infrastructure layer, orchestrated by
``ExecuteAcquisitionJobHandler`` (application layer) — never here.
"""

from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from dataclasses import dataclass

from georisk.contexts.data_acquisition.domain.value_objects import AcquisitionFormat

_EPSG_PATTERN = re.compile(r"^EPSG:\d+$")

#: The four components every complete ESRI Shapefile dataset must have
#: (Sprint B requirement #2) — ``.shp`` (geometry), ``.shx`` (index),
#: ``.dbf`` (attributes), ``.prj`` (CRS, well-known-text). Others
#: (``.cpg``, ``.sbn``, ``.xml``, ...) may be present but are optional.
_REQUIRED_SHAPEFILE_EXTENSIONS = (".shp", ".shx", ".dbf", ".prj")

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


def validate_shapefile_archive(content: bytes) -> tuple[list[str], dict[str, object]]:
    """Requirement #2's completeness check: a Shapefile upload is a ZIP
    archive (Sprint B — a single ``.shp`` file's bytes alone can never be
    "a Shapefile dataset," which is always multi-file by format
    definition). Checks only file NAMES inside the archive — genuine
    geometry/attribute/CRS parsing happens later, in
    ``infrastructure/shapefile_importer.py``, once this structural
    precondition holds.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = archive.namelist()
    except zipfile.BadZipFile:
        return ["Content is not a valid ZIP archive"], {}

    # Case-insensitive, ignoring any directory prefix a zip entry might
    # carry (e.g. "data/parcels.shp") — the "base name" is everything
    # before the last dot of the .shp entry's own filename.
    shp_entries = [n for n in names if n.lower().endswith(".shp")]
    if not shp_entries:
        return ["ZIP archive contains no .shp file"], {}
    if len(shp_entries) > 1:
        return [
            f"ZIP archive must contain exactly one .shp dataset, found {len(shp_entries)}: "
            f"{', '.join(shp_entries)}"
        ], {}

    shp_entry = shp_entries[0]
    base_name = shp_entry[: -len(".shp")]
    lower_names = {n.lower() for n in names}
    missing = [
        f"{base_name}{ext}"
        for ext in _REQUIRED_SHAPEFILE_EXTENSIONS
        if ext != ".shp" and (base_name.lower() + ext) not in lower_names
    ]
    if missing:
        return [
            f"Incomplete Shapefile dataset — missing required component(s): "
            f"{', '.join(missing)}"
        ], {}

    return [], {"shapefile_base_name": base_name, "archive_entries": tuple(names)}


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
    AcquisitionFormat.SHAPEFILE: validate_shapefile_archive,
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
