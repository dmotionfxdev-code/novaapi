"""Sprint C — pure-logic unit tests for the business-formula-free Risk
Layer Generator (``contexts/analysis/infrastructure/risk_layer_generator
.py``): GeoJSON shaping and the generic risk classification thresholds.
No I/O, no GIS library involved (this module never imports one).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from georisk.contexts.analysis.infrastructure.risk_layer_generator import (
    build_risk_layer,
    classify_risk,
)

pytestmark = pytest.mark.unit


def test_classify_risk_bands() -> None:
    assert classify_risk(0.0) == ("LOW", "Low Risk")
    assert classify_risk(0.1101) == ("LOW", "Low Risk")  # FIRAS's own reference FRI
    assert classify_risk(0.1999) == ("LOW", "Low Risk")
    assert classify_risk(0.2) == ("MODERATE", "Moderate Risk")
    assert classify_risk(0.3999) == ("MODERATE", "Moderate Risk")
    assert classify_risk(0.4) == ("HIGH", "High Risk")
    assert classify_risk(0.5999) == ("HIGH", "High Risk")
    assert classify_risk(0.6) == ("SEVERE", "Severe Risk")
    assert classify_risk(1.0) == ("SEVERE", "Severe Risk")


def test_build_risk_layer_rejects_empty_features() -> None:
    with pytest.raises(ValueError, match="at least one real feature"):
        build_risk_layer(
            features=[],
            assessment_id="a1",
            hazard_type="FLOOD",
            stage_type="RISK",
            dataset_id="d1",
            geometry_type="Polygon",
            risk_index=0.11,
            analysis_timestamp=datetime.now(UTC),
            formula_version="fri-multiplicative-v2",
            hazard_specific_attributes={"flood_risk_index": 0.11},
        )


def test_build_risk_layer_attaches_every_required_attribute_to_every_feature() -> None:
    features = [
        {"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0]]]},
         "properties": {"name": "Zone A"}},
        {"geometry": {"type": "Polygon", "coordinates": [[[2, 2], [2, 3], [3, 3], [3, 2]]]},
         "properties": {"name": "Zone B"}},
    ]
    timestamp = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)

    result = build_risk_layer(
        features=features,
        assessment_id="assessment-1",
        hazard_type="FLOOD",
        stage_type="RISK",
        dataset_id="dataset-1",
        geometry_type="Polygon",
        risk_index=0.1101,
        analysis_timestamp=timestamp,
        formula_version="fri-multiplicative-v2",
        hazard_specific_attributes={"flood_risk_index": 0.1101},
    )

    assert result.feature_count == 2
    assert result.geometry_type == "Polygon"
    assert result.risk_index == 0.1101
    assert result.risk_level == "LOW"
    assert result.classification == "Low Risk"
    assert result.bounding_box == pytest.approx((0.0, 0.0, 3.0, 3.0))

    assert result.geojson["type"] == "FeatureCollection"
    assert len(result.geojson["features"]) == 2
    for i, feature in enumerate(result.geojson["features"]):
        assert feature["type"] == "Feature"
        # The exact geometry is passed through verbatim — never fabricated.
        assert feature["geometry"] == features[i]["geometry"]
        props = feature["properties"]
        assert props["assessment_id"] == "assessment-1"
        assert props["hazard_type"] == "FLOOD"
        assert props["stage_type"] == "RISK"
        assert props["risk_index"] == 0.1101
        assert props["risk_level"] == "LOW"
        assert props["classification"] == "Low Risk"
        assert props["analysis_timestamp"] == timestamp.isoformat()
        assert props["formula_version"] == "fri-multiplicative-v2"
        assert props["dataset_id"] == "dataset-1"
        assert props["geometry_type"] == "Polygon"
        assert props["flood_risk_index"] == 0.1101
        # The uploaded feature's OWN attributes are preserved too, tucked
        # under a distinct key so they never collide with the required
        # attribute names above.
        assert props["source_attributes"] == features[i]["properties"]


def test_build_risk_layer_carries_all_hazard_specific_indicators_not_just_risk_index() -> None:
    """Requirement #4's "plus any hazard-specific attributes already
    produced by Analysis" — every indicator the StageResult computed
    (e.g. WRRAS's sub-indices), not only the primary risk index."""
    features = [{"geometry": {"type": "Point", "coordinates": [34.5, -2.3]}, "properties": {}}]

    result = build_risk_layer(
        features=features,
        assessment_id="a1",
        hazard_type="WILDFIRE",
        stage_type="RISK",
        dataset_id="d1",
        geometry_type="Point",
        risk_index=0.0926,
        analysis_timestamp=datetime.now(UTC),
        formula_version="wri-multiplicative-v1",
        hazard_specific_attributes={"wildfire_risk_index": 0.0926},
    )

    props = result.geojson["features"][0]["properties"]
    assert props["wildfire_risk_index"] == 0.0926
