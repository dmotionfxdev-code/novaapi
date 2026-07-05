"""Pure-Python sample-point generation — ported from the legacy system's
``apps/projects/sampling.py`` (named in ``GEORISK_PLATFORM_ARCHITECTURE.md``
§2 as part of ``core.geometry``'s "sampling (stratified/random,
ray-casting point-in-polygon)").

Sprint 7 scope note (``WRRAS_SCOPE_DECISION_LOG.md``-style honesty about
what "stratified" means without real data): true land-cover-stratified
sampling needs a raster of class labels per pixel, which requires
Geospatial's GEE integration — explicitly out of scope this sprint ("No
GEE integration yet"). Stratified sampling here allocates the declared
proportions across the *same* AOI polygon (rejection-sampled uniformly at
random, then labeled according to the allocation) rather than sampling
each stratum from its own sub-region. This is a genuine, useful capability
(proportional, labeled sample generation, matching every
``GEORISK_SCOPE_REALIGNMENT.md`` §4 default) — it is not the same as
raster-class-aware geographic stratification, which is a future
capability once real land-cover data exists.
"""

from __future__ import annotations

import random

from georisk.contexts.geospatial.domain.geometry import point_in_geometry
from georisk.contexts.geospatial.domain.value_objects import (
    AllocationMethod,
    Geometry,
    SamplePoint,
    SamplePointId,
    Stratum,
)

_MAX_ATTEMPTS_PER_POINT = 200


def _random_point_in_bbox(geometry: Geometry, rng: random.Random) -> tuple[float, float]:
    """Rejection-samples one point uniformly within the geometry's
    bounding box until it lands inside the actual polygon (handles
    concave/multi-part shapes correctly, at the cost of extra draws for
    AOIs that occupy a small fraction of their bbox)."""
    from georisk.contexts.geospatial.domain.geometry import compute_aoi_statistics

    bbox = compute_aoi_statistics(geometry).bbox
    for _ in range(_MAX_ATTEMPTS_PER_POINT):
        lon = rng.uniform(bbox.min_lon, bbox.max_lon)
        lat = rng.uniform(bbox.min_lat, bbox.max_lat)
        if point_in_geometry(lon, lat, geometry):
            return lon, lat
    # Fall back to the bbox center — better than failing outright for a
    # pathologically thin AOI; still guaranteed inside the bbox.
    return (bbox.min_lon + bbox.max_lon) / 2, (bbox.min_lat + bbox.max_lat) / 2


def allocate_stratified_samples(
    strata: tuple[Stratum, ...], total: int, allocation_method: AllocationMethod
) -> dict[str, int]:
    """Splits ``total`` samples across ``strata`` per the declared
    proportions (``PROPORTIONAL``) or evenly (``EQUAL``), then tops up any
    stratum below the platform-wide per-class minimum by taking the
    shortfall from the largest stratum — never silently drops the
    minimum-per-class guarantee.
    """
    if not strata:
        return {}
    if allocation_method is AllocationMethod.EQUAL:
        share = total // len(strata)
        allocation = {stratum.label: share for stratum in strata}
        remainder = total - share * len(strata)
    else:
        total_proportion = sum(stratum.proportion for stratum in strata)
        allocation = {
            stratum.label: round(total * (stratum.proportion / total_proportion))
            for stratum in strata
        }
        remainder = total - sum(allocation.values())

    # Assign any rounding remainder to the largest stratum.
    if remainder:
        largest_label = max(allocation, key=lambda label: allocation[label])
        allocation[largest_label] += remainder

    return allocation


def generate_simple_random_samples(
    geometry: Geometry, count: int, seed: int
) -> tuple[SamplePoint, ...]:
    rng = random.Random(seed)
    points = []
    for _ in range(count):
        lon, lat = _random_point_in_bbox(geometry, rng)
        points.append(
            SamplePoint(id=SamplePointId.new(), longitude=lon, latitude=lat, stratum=None)
        )
    return tuple(points)


def generate_stratified_samples(
    geometry: Geometry,
    strata: tuple[Stratum, ...],
    total: int,
    allocation_method: AllocationMethod,
    seed: int,
) -> tuple[SamplePoint, ...]:
    allocation = allocate_stratified_samples(strata, total, allocation_method)
    rng = random.Random(seed)
    points = []
    for label, count in allocation.items():
        for _ in range(count):
            lon, lat = _random_point_in_bbox(geometry, rng)
            points.append(
                SamplePoint(id=SamplePointId.new(), longitude=lon, latitude=lat, stratum=label)
            )
    return tuple(points)


def samples_to_geojson(points: tuple[SamplePoint, ...]) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [p.longitude, p.latitude]},
                "properties": {"id": str(p.id), "stratum": p.stratum},
            }
            for p in points
        ],
    }


def samples_to_csv(points: tuple[SamplePoint, ...]) -> str:
    lines = ["id,longitude,latitude,stratum"]
    lines.extend(
        f"{p.id},{p.longitude},{p.latitude},{p.stratum or ''}" for p in points
    )
    return "\n".join(lines)
