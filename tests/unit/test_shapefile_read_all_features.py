"""Sprint C — unit tests for ``read_all_features`` (extends Sprint B's
``infrastructure/shapefile_importer.py``): genuinely reads EVERY feature's
real geometry + attributes, not just the first (Sprint B's
``parse_shapefile_archive`` only ever needed one representative row).
Pure I/O over an in-memory ZIP — no database needed, unlike
``tests/integration/test_shapefile_import.py``'s handler-level tests.
"""

from __future__ import annotations

import io
import zipfile

import pytest
import shapefile as pyshp

from georisk.contexts.data_acquisition.domain.errors import CorruptedShapefileError
from georisk.contexts.data_acquisition.infrastructure.shapefile_importer import read_all_features

pytestmark = pytest.mark.unit

_WGS84_PRJ = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
)


def _zip_archive(base_name: str, components: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for ext, content in components.items():
            archive.writestr(f"{base_name}.{ext}", content)
    return buf.getvalue()


def _polygon_zip() -> bytes:
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = pyshp.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=pyshp.POLYGON)
    writer.field("name", "C", size=40)
    writer.field("risk", "N", decimal=2)
    writer.poly([[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]])
    writer.record("Zone A", 0.82)
    writer.poly([[[20, 20], [20, 30], [30, 30], [30, 20], [20, 20]]])
    writer.record("Zone B", 0.45)
    writer.close()
    return _zip_archive(
        "parcels", {"shp": shp.getvalue(), "shx": shx.getvalue(), "dbf": dbf.getvalue(),
                    "prj": _WGS84_PRJ.encode()}
    )


def _point_zip() -> bytes:
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = pyshp.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=pyshp.POINT)
    writer.field("station", "C", size=40)
    writer.point(36.8, -1.3)
    writer.record("Nairobi")
    writer.point(39.2, -6.8)
    writer.record("Dar es Salaam")
    writer.close()
    return _zip_archive(
        "stations", {"shp": shp.getvalue(), "shx": shx.getvalue(), "dbf": dbf.getvalue(),
                     "prj": _WGS84_PRJ.encode()}
    )


def test_read_all_features_returns_every_feature_not_just_first() -> None:
    features = read_all_features(_polygon_zip())
    assert len(features) == 2
    assert features[0].properties == {"name": "Zone A", "risk": 0.82}
    assert features[1].properties == {"name": "Zone B", "risk": 0.45}


def test_read_all_features_geometry_is_genuine_geojson_matching_uploaded_coordinates() -> None:
    features = read_all_features(_polygon_zip())
    assert features[0].geometry["type"] == "Polygon"
    # The exact coordinates genuinely uploaded — never fabricated/rounded.
    ring = features[0].geometry["coordinates"][0]
    assert (0.0, 0.0) in [tuple(pt) for pt in ring]
    assert (10.0, 10.0) in [tuple(pt) for pt in ring]

    second_ring = features[1].geometry["coordinates"][0]
    assert (20.0, 20.0) in [tuple(pt) for pt in second_ring]
    assert (30.0, 30.0) in [tuple(pt) for pt in second_ring]


def test_read_all_features_point_geometry() -> None:
    features = read_all_features(_point_zip())
    assert len(features) == 2
    assert features[0].geometry == {"type": "Point", "coordinates": (36.8, -1.3)}
    assert features[0].properties == {"station": "Nairobi"}
    assert features[1].geometry == {"type": "Point", "coordinates": (39.2, -6.8)}


def test_read_all_features_raises_corrupted_error_for_garbage_archive() -> None:
    garbage = _zip_archive(
        "garbage",
        {"shp": b"\x00" * 10, "shx": b"\x00" * 10, "dbf": b"\x00" * 10, "prj": _WGS84_PRJ.encode()},
    )
    with pytest.raises(CorruptedShapefileError):
        read_all_features(garbage)
