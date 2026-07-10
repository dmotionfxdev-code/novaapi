"""Unit tests for the Dataset Import Pipeline's pure format/CRS/geometry
validators (Sprint 13 requirement #4) and the Provider Registry
(requirement #2) — pure logic, no I/O.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from georisk.contexts.data_acquisition.application.ports import (
    FetchResult,
    LocalUploadProvider,
    ProviderRegistry,
)
from georisk.contexts.data_acquisition.domain.errors import NoProviderRegisteredError
from georisk.contexts.data_acquisition.domain.validation import (
    validate_crs,
    validate_csv,
    validate_dataset_content,
    validate_geojson,
    validate_geotiff,
    validate_json,
    validate_shapefile_archive,
)
from georisk.contexts.data_acquisition.domain.value_objects import AcquisitionFormat, DataProvider

pytestmark = pytest.mark.unit


def test_validate_crs_accepts_epsg_form() -> None:
    assert validate_crs("EPSG:4326") == []


def test_validate_crs_rejects_blank() -> None:
    assert validate_crs("   ") != []


def test_validate_crs_rejects_malformed() -> None:
    assert validate_crs("WGS84") != []


def test_validate_geojson_feature_collection() -> None:
    content = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}},
                {"type": "Feature", "geometry": {"type": "Point", "coordinates": [1, 1]}},
            ],
        }
    ).encode()
    errors, metadata = validate_geojson(content)
    assert errors == []
    assert metadata == {"feature_count": 2}


def test_validate_geojson_rejects_malformed_json() -> None:
    errors, _ = validate_geojson(b"{not json")
    assert errors


def test_validate_geojson_rejects_unrecognized_type() -> None:
    errors, _ = validate_geojson(json.dumps({"type": "NotAThing"}).encode())
    assert errors


def test_validate_csv_extracts_row_and_column_counts() -> None:
    content = b"name,value\nrainfall,10\ntemperature,20\n"
    errors, metadata = validate_csv(content)
    assert errors == []
    assert metadata == {"column_count": 2, "row_count": 2}


def test_validate_csv_rejects_empty_content() -> None:
    errors, _ = validate_csv(b"")
    assert errors


def test_validate_geotiff_accepts_little_endian_magic() -> None:
    content = b"II*\x00" + b"\x00" * 20
    errors, metadata = validate_geotiff(content)
    assert errors == []
    assert metadata["byte_size"] == len(content)


def test_validate_geotiff_rejects_non_tiff_content() -> None:
    errors, _ = validate_geotiff(b"not a tiff file at all")
    assert errors


def _zip_of(names: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for name, content in names.items():
            archive.writestr(name, content)
    return buf.getvalue()


def test_validate_shapefile_archive_accepts_complete_archive() -> None:
    # Sprint B: real completeness check — a well-formed ZIP naming all
    # four required components. Content itself is irrelevant here (that's
    # ``infrastructure/shapefile_importer.py``'s job, not this pure-domain
    # structural check) — only file names matter.
    content = _zip_of(
        {
            "parcels.shp": b"shp-bytes",
            "parcels.shx": b"shx-bytes",
            "parcels.dbf": b"dbf-bytes",
            "parcels.prj": b"prj-bytes",
        }
    )
    errors, metadata = validate_shapefile_archive(content)
    assert errors == []
    assert metadata["shapefile_base_name"] == "parcels"


def test_validate_shapefile_archive_rejects_not_a_zip() -> None:
    errors, _ = validate_shapefile_archive(b"\x00\x00\x27\x0a" + b"\x00" * 96)
    assert errors
    assert "not a valid ZIP archive" in errors[0]


def test_validate_shapefile_archive_rejects_missing_dbf() -> None:
    content = _zip_of({"parcels.shp": b"x", "parcels.shx": b"x", "parcels.prj": b"x"})
    errors, _ = validate_shapefile_archive(content)
    assert errors
    assert "parcels.dbf" in errors[0]


def test_validate_shapefile_archive_rejects_missing_shx() -> None:
    content = _zip_of({"parcels.shp": b"x", "parcels.dbf": b"x", "parcels.prj": b"x"})
    errors, _ = validate_shapefile_archive(content)
    assert errors
    assert "parcels.shx" in errors[0]


def test_validate_shapefile_archive_rejects_missing_prj() -> None:
    content = _zip_of({"parcels.shp": b"x", "parcels.shx": b"x", "parcels.dbf": b"x"})
    errors, _ = validate_shapefile_archive(content)
    assert errors
    assert "parcels.prj" in errors[0]


def test_validate_shapefile_archive_rejects_no_shp() -> None:
    content = _zip_of({"readme.txt": b"x"})
    errors, _ = validate_shapefile_archive(content)
    assert errors
    assert "no .shp file" in errors[0]


def test_validate_shapefile_archive_rejects_multiple_shp() -> None:
    content = _zip_of(
        {
            "a.shp": b"x",
            "a.shx": b"x",
            "a.dbf": b"x",
            "a.prj": b"x",
            "b.shp": b"x",
            "b.shx": b"x",
            "b.dbf": b"x",
            "b.prj": b"x",
        }
    )
    errors, _ = validate_shapefile_archive(content)
    assert errors
    assert "exactly one .shp" in errors[0]


def test_validate_json_accepts_any_valid_json() -> None:
    errors, metadata = validate_json(b'{"foo": "bar"}')
    assert errors == []
    assert metadata == {"json_type": "dict"}


def test_validate_dataset_content_merges_format_and_crs_errors() -> None:
    outcome = validate_dataset_content(format=AcquisitionFormat.JSON, content=b"{bad", crs="")
    assert outcome.is_valid is False
    assert len(outcome.errors) == 2


def test_validate_dataset_content_success() -> None:
    outcome = validate_dataset_content(
        format=AcquisitionFormat.CSV, content=b"a,b\n1,2\n", crs="EPSG:4326"
    )
    assert outcome.is_valid is True
    assert outcome.errors == ()
    assert outcome.extracted_metadata == {"column_count": 2, "row_count": 1}


def test_provider_registry_resolves_registered_provider() -> None:
    registry = ProviderRegistry()
    adapter = LocalUploadProvider()
    registry.register(DataProvider.LOCAL_UPLOAD, adapter)
    assert registry.resolve(DataProvider.LOCAL_UPLOAD) is adapter


def test_provider_registry_raises_for_unregistered_provider() -> None:
    registry = ProviderRegistry()
    with pytest.raises(NoProviderRegisteredError):
        registry.resolve(DataProvider.NASA)


def test_local_upload_provider_returns_provided_content() -> None:
    result = asyncio.run(
        LocalUploadProvider().fetch(source_reference="file.csv", raw_content=b"a,b\n1,2\n")
    )
    assert result == FetchResult(success=True, content=b"a,b\n1,2\n", error=None)


def test_local_upload_provider_fails_without_content() -> None:
    result = asyncio.run(LocalUploadProvider().fetch(source_reference="file.csv"))
    assert result.success is False


# Sprint 13's interface-only ``GoogleEarthEngineProvider`` stub (tested
# here previously) was superseded in Sprint 14 by a real connector in
# ``infrastructure/gee_connector.py`` — see
# ``tests/unit/test_gee_connector.py`` for its honest-failure-path tests.
