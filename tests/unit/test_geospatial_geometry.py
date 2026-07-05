"""Unit tests for the Geospatial context's pure geometry math — no I/O.
Reference values hand-checked against known shapes (a 1-degree-square
polygon near the equator, where degree-to-meter scaling is close to
uniform) so any future change to the formulas is a deliberate, visible
diff.
"""

from __future__ import annotations

import pytest

from georisk.contexts.geospatial.domain.geometry import (
    compute_aoi_statistics,
    haversine_distance,
    point_in_geometry,
    rectangle_to_geojson,
    ring_bbox,
    ring_centroid,
)
from georisk.contexts.geospatial.domain.value_objects import Geometry

pytestmark = pytest.mark.unit

_SQUARE_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]],
}


def test_haversine_distance_one_degree_latitude_is_about_111km() -> None:
    distance = haversine_distance(0.0, 0.0, 1.0, 0.0)
    assert distance == pytest.approx(111_195, abs=200)


def test_geometry_rejects_non_polygon_type() -> None:
    with pytest.raises(ValueError, match="Polygon"):
        Geometry(geojson={"type": "Point", "coordinates": [0.0, 0.0]})


def test_geometry_rejects_unclosed_ring() -> None:
    with pytest.raises(ValueError, match="closed"):
        Geometry(geojson={"type": "Polygon", "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0]]]})


def test_geometry_accepts_valid_square() -> None:
    geometry = Geometry(geojson=_SQUARE_GEOJSON)
    assert geometry.exterior_rings() == [_SQUARE_GEOJSON["coordinates"][0]]


def test_ring_bbox_matches_square_corners() -> None:
    bbox = ring_bbox(_SQUARE_GEOJSON["coordinates"][0])
    assert bbox == (0.0, 0.0, 1.0, 1.0)


def test_ring_centroid_of_square_is_its_middle() -> None:
    lon, lat = ring_centroid(_SQUARE_GEOJSON["coordinates"][0])
    assert lon == pytest.approx(0.5)
    assert lat == pytest.approx(0.5)


def test_compute_aoi_statistics_area_of_one_degree_square_near_equator() -> None:
    geometry = Geometry(geojson=_SQUARE_GEOJSON)
    stats = compute_aoi_statistics(geometry)
    # ~111,320m x ~111,320m at the equator (cos(0.5 deg) ~ 1).
    assert stats.area_m2 == pytest.approx(111_320 * 111_320, rel=0.01)
    assert stats.centroid.longitude == pytest.approx(0.5)
    assert stats.centroid.latitude == pytest.approx(0.5)
    assert stats.bbox.min_lon == 0.0
    assert stats.bbox.max_lat == 1.0


def test_point_in_geometry_true_for_interior_point() -> None:
    geometry = Geometry(geojson=_SQUARE_GEOJSON)
    assert point_in_geometry(0.5, 0.5, geometry) is True


def test_point_in_geometry_false_for_exterior_point() -> None:
    geometry = Geometry(geojson=_SQUARE_GEOJSON)
    assert point_in_geometry(2.0, 2.0, geometry) is False


def test_rectangle_to_geojson_produces_a_closed_valid_ring() -> None:
    geojson = rectangle_to_geojson(0.0, 0.0, 2.0, 3.0)
    geometry = Geometry(geojson=geojson)  # raises if invalid
    stats = compute_aoi_statistics(geometry)
    assert stats.bbox.min_lon == 0.0
    assert stats.bbox.max_lon == 2.0
    assert stats.bbox.max_lat == 3.0


def test_multipolygon_statistics_sum_across_parts() -> None:
    multi = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]],
            [[[10.0, 10.0], [10.0, 11.0], [11.0, 11.0], [11.0, 10.0], [10.0, 10.0]]],
        ],
    }
    geometry = Geometry(geojson=multi)
    stats = compute_aoi_statistics(geometry)
    single_square_area = compute_aoi_statistics(Geometry(geojson=_SQUARE_GEOJSON)).area_m2
    # Second square is at a higher latitude, so its area differs slightly
    # (cos(lat) scaling) — total must still exceed either part alone.
    assert stats.area_m2 > single_square_area
