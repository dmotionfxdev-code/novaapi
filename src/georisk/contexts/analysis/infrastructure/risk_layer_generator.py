"""Sprint C — the Risk Layer Generator (requirement #1): converts a
completed Analysis ``StageResult`` plus a set of genuinely-uploaded
geometries (Sprint B) into a real GeoJSON ``FeatureCollection``.

**Contains no business formulas** — it never computes a risk index, never
re-derives FIRAS/WRRAS indicator math, and never touches
``strategies/firas``/``strategies/wrras``. Every numeric value placed into
a feature's properties is copied verbatim from the ``StageResult`` this
module is handed; this module's only original logic is (1) shaping plain
dicts into an RFC 7946 ``FeatureCollection``, and (2) a simple, generic,
hazard-agnostic risk_level/classification bucketing — a PRESENTATION
convenience (so a map can colour features without every consumer
reimplementing the same thresholds), explicitly not a substitute for or
duplicate of FIRAS's/WRRAS's own risk formulas, which remain the only
source of the underlying ``risk_index`` value.

Deliberately importable from ``contexts.analysis`` freely: unlike
``data_acquisition/infrastructure/shapefile_importer.py``, this module
never imports ``pyogrio``/``shapely`` or any other GIS library — it only
ever receives already-GeoJSON-shaped geometry dicts (produced by that
other module, in the OTHER bounded context) via its caller, the
composition-root ``api/risk_layer_ports.py``. This keeps the import-linter's
"External GIS/GEE libraries only imported behind data_acquisition's
infrastructure layer" contract satisfied without needing to add
``contexts.analysis`` to its exemption list.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

#: Generic, hazard-agnostic risk classification thresholds — a
#: visualization convenience only. FIRAS's/WRRAS's own risk indices are
#: both normalized, multiplicative products of factors in [0, 1] (FRI/WRI
#: in this platform's own reference runs land well under 0.2), so these
#: bands are deliberately wide at the low end rather than a naive
#: even four-way split of [0, 1]. Named and documented here exactly
#: because it's a judgment call, not a formula this sprint was told to
#: implement — a future sprint may replace it with a
#: per-hazard-configurable scheme without touching FIRAS/WRRAS.
_RISK_BANDS: tuple[tuple[float, str, str], ...] = (
    (0.2, "LOW", "Low Risk"),
    (0.4, "MODERATE", "Moderate Risk"),
    (0.6, "HIGH", "High Risk"),
)
_SEVERE = ("SEVERE", "Severe Risk")


def classify_risk(risk_index: float) -> tuple[str, str]:
    """Returns ``(risk_level, classification)`` — e.g. ``("HIGH", "High
    Risk")``. Pure, deterministic, and total over the real number line
    (values outside [0, 1], however produced, still classify instead of
    raising, since this is presentation logic, not input validation)."""
    for threshold, level, label in _RISK_BANDS:
        if risk_index < threshold:
            return level, label
    return _SEVERE


@dataclass(frozen=True, slots=True)
class RiskLayerFeatureCollection:
    """The generator's output: a real RFC 7946 ``FeatureCollection``
    (``geojson``) plus the metadata needed to persist/describe it without
    re-parsing the GeoJSON body."""

    geojson: dict[str, Any]
    feature_count: int
    geometry_type: str
    bounding_box: tuple[float, float, float, float]
    risk_index: float
    risk_level: str
    classification: str


def _bounding_box_of(features: list[dict]) -> tuple[float, float, float, float]:
    """Computed here, from the SAME geometries being placed into the
    FeatureCollection — not re-fetched from Data Acquisition's own
    already-recorded bounding box, since that one describes the ENTIRE
    source dataset, not necessarily this layer's feature set (a future
    filtering step could select a subset)."""
    xs: list[float] = []
    ys: list[float] = []

    def _walk(coords: object) -> None:
        if not isinstance(coords, list | tuple) or not coords:
            return
        first = coords[0]
        if isinstance(first, list | tuple):
            for item in coords:
                _walk(item)
        elif len(coords) >= 2:
            xs.append(float(coords[0]))
            ys.append(float(coords[1]))

    for feature in features:
        _walk(feature["geometry"].get("coordinates"))
    if not xs or not ys:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def build_risk_layer(
    *,
    features: list[dict],
    assessment_id: str,
    hazard_type: str,
    stage_type: str,
    dataset_id: str,
    geometry_type: str,
    risk_index: float,
    analysis_timestamp: datetime,
    formula_version: str,
    hazard_specific_attributes: dict[str, float],
) -> RiskLayerFeatureCollection:
    """Requirement #4: attaches every required attribute to EVERY feature
    — ``risk_index``/``risk_level``/``classification`` are assessment-wide
    facts (FIRAS/WRRAS compute one scalar risk index per assessment, not
    per-feature), so every genuinely-uploaded geometry is attributed with
    the SAME real computed value, never a fabricated per-feature
    variation the underlying calculation doesn't actually produce.
    ``features`` must be non-empty (Sprint B never catalogs an empty
    Shapefile — see ``EmptyShapefileDatasetError`` — so an empty list
    here would mean the caller resolved a geometry source incorrectly,
    a caller bug, not a legitimate empty-layer case).
    """
    if not features:
        raise ValueError("build_risk_layer requires at least one real feature's geometry")

    risk_level, classification = classify_risk(risk_index)
    timestamp = analysis_timestamp.isoformat()

    geojson_features = []
    for feature in features:
        properties: dict[str, Any] = {
            "assessment_id": assessment_id,
            "hazard_type": hazard_type,
            "stage_type": stage_type,
            "risk_index": risk_index,
            "risk_level": risk_level,
            "classification": classification,
            "analysis_timestamp": timestamp,
            "formula_version": formula_version,
            "dataset_id": dataset_id,
            "geometry_type": geometry_type,
            **hazard_specific_attributes,
            "source_attributes": feature["properties"],
        }
        geojson_features.append(
            {"type": "Feature", "geometry": feature["geometry"], "properties": properties}
        )

    geojson = {"type": "FeatureCollection", "features": geojson_features}
    return RiskLayerFeatureCollection(
        geojson=geojson,
        feature_count=len(geojson_features),
        geometry_type=geometry_type,
        bounding_box=_bounding_box_of(features),
        risk_index=risk_index,
        risk_level=risk_level,
        classification=classification,
    )
