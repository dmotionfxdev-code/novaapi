"""Pure-Python geometry math — ported from the legacy system's
``apps/projects/geometry.py`` (named directly in
``GEORISK_PLATFORM_ARCHITECTURE.md`` §2 as ``core.geometry``'s source:
"Haversine distance, Shoelace polygon area/perimeter/centroid... AOI
parsing"). No GDAL/Shapely/PostGIS dependency — every AOI operation this
sprint needs (validity, area, perimeter, centroid, bounding box,
point-in-polygon for sampling) is planar-enough at AOI scale to not
justify one, matching this codebase's established policy of not adding a
heavy dependency until a second consumer genuinely needs it
(``strategies/firas/ewm.py``'s docstring sets the same precedent).

Area/perimeter use a simple mean-latitude degree-to-meter scaling, not a
full geodesic projection — adequate for the AOI sizes this platform
targets (project/site scale, not continental), and consistent with the
legacy implementation this is ported from.
"""

from __future__ import annotations

import math

from georisk.contexts.geospatial.domain.value_objects import BoundingBox, Centroid, Geometry

_EARTH_RADIUS_M = 6_371_000.0
_METERS_PER_DEGREE_LAT = 111_320.0


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in meters."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(min(1.0, a)))


def _meters_per_degree(mean_latitude: float) -> tuple[float, float]:
    lon_m = _METERS_PER_DEGREE_LAT * math.cos(math.radians(mean_latitude))
    return lon_m, _METERS_PER_DEGREE_LAT


def _ring_points(ring: list) -> list[tuple[float, float]]:
    return [(float(p[0]), float(p[1])) for p in ring]


def ring_area_m2(ring: list) -> float:
    """Shoelace formula, in a locally-scaled meter plane (mean-latitude
    degree-to-meter conversion, not a full geodesic projection)."""
    points = _ring_points(ring)
    if len(points) < 4:
        return 0.0
    mean_lat = sum(p[1] for p in points) / len(points)
    lon_m, lat_m = _meters_per_degree(mean_lat)
    scaled = [(lon * lon_m, lat * lat_m) for lon, lat in points]
    area = 0.0
    for i in range(len(scaled) - 1):
        x1, y1 = scaled[i]
        x2, y2 = scaled[i + 1]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def ring_perimeter_m(ring: list) -> float:
    points = _ring_points(ring)
    total = 0.0
    for i in range(len(points) - 1):
        lon1, lat1 = points[i]
        lon2, lat2 = points[i + 1]
        total += haversine_distance(lat1, lon1, lat2, lon2)
    return total


def ring_centroid(ring: list) -> tuple[float, float]:
    """Simple vertex-average centroid (excluding the closing duplicate
    vertex) — an approximation, not the area-weighted polygon centroid;
    adequate for map-display and sampling-bbox purposes."""
    points = _ring_points(ring)
    if tuple(points[0]) == tuple(points[-1]):
        points = points[:-1]
    lon = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lon, lat


def ring_bbox(ring: list) -> tuple[float, float, float, float]:
    points = _ring_points(ring)
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return min(lons), min(lats), max(lons), max(lats)


def point_in_ring(longitude: float, latitude: float, ring: list) -> bool:
    """Ray-casting point-in-polygon test against one ring."""
    points = _ring_points(ring)
    n = len(points)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = points[i]
        xj, yj = points[j]
        intersects = (yi > latitude) != (yj > latitude) and longitude < (xj - xi) * (
            latitude - yi
        ) / (yj - yi + 1e-15) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


def point_in_geometry(longitude: float, latitude: float, geometry: Geometry) -> bool:
    """True if the point falls within any of the geometry's exterior
    rings (holes are not modeled — see ``Geometry.exterior_rings``'s
    docstring)."""
    return any(point_in_ring(longitude, latitude, ring) for ring in geometry.exterior_rings())


class AoiStatistics:
    __slots__ = ("area_m2", "perimeter_m", "centroid", "bbox")

    def __init__(
        self, area_m2: float, perimeter_m: float, centroid: Centroid, bbox: BoundingBox
    ) -> None:
        self.area_m2 = area_m2
        self.perimeter_m = perimeter_m
        self.centroid = centroid
        self.bbox = bbox


def compute_aoi_statistics(geometry: Geometry) -> AoiStatistics:
    """Aggregates area/perimeter/centroid/bbox across every exterior ring
    (a ``MultiPolygon`` sums area/perimeter across its parts and takes
    the union bbox; centroid is the area-weighted mean of each ring's own
    centroid)."""
    rings = geometry.exterior_rings()
    ring_stats = [
        (ring_area_m2(ring), ring_perimeter_m(ring), ring_centroid(ring), ring_bbox(ring))
        for ring in rings
    ]
    total_area = sum(area for area, _, _, _ in ring_stats)
    total_perimeter = sum(perimeter for _, perimeter, _, _ in ring_stats)

    if total_area > 0:
        centroid_lon = sum(area * centroid[0] for area, _, centroid, _ in ring_stats) / total_area
        centroid_lat = sum(area * centroid[1] for area, _, centroid, _ in ring_stats) / total_area
    else:
        centroid_lon = sum(centroid[0] for _, _, centroid, _ in ring_stats) / len(ring_stats)
        centroid_lat = sum(centroid[1] for _, _, centroid, _ in ring_stats) / len(ring_stats)

    min_lon = min(bbox[0] for _, _, _, bbox in ring_stats)
    min_lat = min(bbox[1] for _, _, _, bbox in ring_stats)
    max_lon = max(bbox[2] for _, _, _, bbox in ring_stats)
    max_lat = max(bbox[3] for _, _, _, bbox in ring_stats)

    return AoiStatistics(
        area_m2=round(total_area, 2),
        perimeter_m=round(total_perimeter, 2),
        centroid=Centroid(longitude=round(centroid_lon, 6), latitude=round(centroid_lat, 6)),
        bbox=BoundingBox(min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat),
    )


def rectangle_to_geojson(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float
) -> dict:
    """Builds a closed-ring GeoJSON Polygon from a bounding rectangle —
    the ``RECTANGLE`` ``AoiSource`` path."""
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]
        ],
    }
