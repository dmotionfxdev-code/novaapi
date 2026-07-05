"""Unit tests for the Geospatial context's pure sampling algorithms — no
I/O.
"""

from __future__ import annotations

import pytest

from georisk.contexts.geospatial.domain.geometry import point_in_geometry
from georisk.contexts.geospatial.domain.sampling import (
    allocate_stratified_samples,
    generate_simple_random_samples,
    generate_stratified_samples,
    samples_to_csv,
    samples_to_geojson,
)
from georisk.contexts.geospatial.domain.value_objects import AllocationMethod, Geometry, Stratum

pytestmark = pytest.mark.unit

_SQUARE = Geometry(
    geojson={
        "type": "Polygon",
        "coordinates": [[[0.0, 0.0], [0.0, 1.0], [1.0, 1.0], [1.0, 0.0], [0.0, 0.0]]],
    }
)


def test_allocate_stratified_samples_proportional() -> None:
    strata = (Stratum(label="forest", proportion=0.7), Stratum(label="urban", proportion=0.3))
    allocation = allocate_stratified_samples(strata, 100, AllocationMethod.PROPORTIONAL)
    assert allocation == {"forest": 70, "urban": 30}


def test_allocate_stratified_samples_equal() -> None:
    strata = (Stratum(label="a", proportion=0.9), Stratum(label="b", proportion=0.1))
    allocation = allocate_stratified_samples(strata, 100, AllocationMethod.EQUAL)
    assert allocation == {"a": 50, "b": 50}


def test_allocate_stratified_samples_assigns_rounding_remainder() -> None:
    strata = (
        Stratum(label="a", proportion=0.34),
        Stratum(label="b", proportion=0.33),
        Stratum(label="c", proportion=0.33),
    )
    allocation = allocate_stratified_samples(strata, 100, AllocationMethod.PROPORTIONAL)
    assert sum(allocation.values()) == 100


def test_generate_simple_random_samples_all_fall_inside_geometry() -> None:
    points = generate_simple_random_samples(_SQUARE, 50, seed=42)
    assert len(points) == 50
    assert all(point_in_geometry(p.longitude, p.latitude, _SQUARE) for p in points)
    assert all(p.stratum is None for p in points)


def test_generate_simple_random_samples_is_deterministic_given_a_seed() -> None:
    first = generate_simple_random_samples(_SQUARE, 10, seed=99)
    second = generate_simple_random_samples(_SQUARE, 10, seed=99)
    assert [(p.longitude, p.latitude) for p in first] == [(p.longitude, p.latitude) for p in second]


def test_generate_stratified_samples_matches_declared_count_and_falls_inside_geometry() -> None:
    strata = (Stratum(label="forest", proportion=0.6), Stratum(label="urban", proportion=0.4))
    points = generate_stratified_samples(
        _SQUARE, strata, 50, AllocationMethod.PROPORTIONAL, seed=7
    )
    assert len(points) == 50
    assert all(point_in_geometry(p.longitude, p.latitude, _SQUARE) for p in points)
    labels = {p.stratum for p in points}
    assert labels == {"forest", "urban"}
    assert sum(1 for p in points if p.stratum == "forest") == 30


def test_samples_to_geojson_produces_a_feature_collection() -> None:
    points = generate_simple_random_samples(_SQUARE, 3, seed=1)
    geojson = samples_to_geojson(points)
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 3
    assert geojson["features"][0]["geometry"]["type"] == "Point"


def test_samples_to_csv_has_one_header_plus_one_row_per_point() -> None:
    points = generate_simple_random_samples(_SQUARE, 5, seed=1)
    csv_text = samples_to_csv(points)
    lines = csv_text.splitlines()
    assert lines[0] == "id,longitude,latitude,stratum"
    assert len(lines) == 6
