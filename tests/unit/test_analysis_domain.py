"""Domain-layer unit tests for the ``StageResult`` aggregate and its value
objects — pure logic, no I/O.
"""

from __future__ import annotations

import pytest

from georisk.contexts.analysis.domain.entities import StageResult
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    ConfidenceTier,
    HazardType,
    Indicator,
    IndicatorSet,
    StageResultStatus,
    StageType,
    confidence_tier_for_sample_size,
)
from georisk.contexts.identity.domain.value_objects import TenantId

pytestmark = pytest.mark.unit


def test_confidence_tier_thresholds() -> None:
    assert confidence_tier_for_sample_size(1) is ConfidenceTier.LOW
    assert confidence_tier_for_sample_size(2) is ConfidenceTier.MODERATE
    assert confidence_tier_for_sample_size(4) is ConfidenceTier.MODERATE
    assert confidence_tier_for_sample_size(5) is ConfidenceTier.HIGH
    assert confidence_tier_for_sample_size(100) is ConfidenceTier.HIGH


def test_indicator_set_get_and_value() -> None:
    indicator_set = IndicatorSet(
        indicators=(Indicator(code="flood_hazard_index", value=0.565, unit="index"),)
    )
    assert indicator_set.value("flood_hazard_index") == 0.565
    assert indicator_set.get("nonexistent") is None
    assert indicator_set.value("nonexistent") is None


def test_indicator_set_as_dict() -> None:
    indicator_set = IndicatorSet(
        indicators=(
            Indicator(code="a", value=0.1),
            Indicator(code="b", value=0.2),
        )
    )
    assert indicator_set.as_dict() == {"a": 0.1, "b": 0.2}


def test_stage_result_complete_produces_computed_event() -> None:
    indicators = IndicatorSet(indicators=(Indicator(code="flood_hazard_index", value=0.565),))
    result, event = StageResult.complete(
        tenant_id=TenantId.new(),
        assessment_id="11111111-1111-1111-1111-111111111111",
        hazard_type=HazardType.FLOOD,
        stage_type=StageType.HAZARD,
        version=1,
        indicators=indicators,
        confidence_tier=ConfidenceTier.LOW,
        snapshot=ComputationSnapshot(inputs={"rainfall_index": 0.65}),
        issued_by="system:workflow-engine",
        strategy_version="firas-2.0",
        formula_version="fhi-weighted-linear-v1",
    )
    assert result.status == StageResultStatus.COMPLETE
    assert result.error is None
    assert result.strategy_version == "firas-2.0"
    assert result.formula_version == "fhi-weighted-linear-v1"
    assert event.event_type == "analysis.StageResultComputed"
    assert event.indicators == {"flood_hazard_index": 0.565}
    assert event.strategy_version == "firas-2.0"
    assert event.formula_version == "fhi-weighted-linear-v1"


def test_stage_result_failed_produces_failed_event_with_no_indicators() -> None:
    result, event = StageResult.failed(
        tenant_id=TenantId.new(),
        assessment_id="11111111-1111-1111-1111-111111111111",
        hazard_type=HazardType.FLOOD,
        stage_type=StageType.RISK,
        version=1,
        snapshot=ComputationSnapshot(inputs={}),
        error="missing prior stage result",
        issued_by="system:workflow-engine",
    )
    assert result.status == StageResultStatus.FAILED
    assert result.indicators is None
    assert result.confidence_tier is None
    assert result.strategy_version is None
    assert result.formula_version is None
    assert event.event_type == "analysis.StageResultFailed"
    assert event.error == "missing prior stage result"


def test_stage_result_has_no_method_other_than_complete_and_failed() -> None:
    """Structural proof, matching Sprint 4's precedent after the
    field/classmethod name collision bug: neither classmethod name
    collides with a field name here (``complete``/``failed`` vs.
    ``status``/``indicators``/``error``/...)."""
    public_methods = {
        name
        for name in vars(StageResult)
        if not name.startswith("_") and callable(getattr(StageResult, name))
    }
    assert public_methods == {"complete", "failed"}
