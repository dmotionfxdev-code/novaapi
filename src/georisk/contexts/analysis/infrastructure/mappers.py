"""Maps between the ``StageResult`` domain entity and its SQLAlchemy ORM
representation. Free functions, not methods on either side (same pattern
as every prior context).
"""

from __future__ import annotations

import uuid as uuid_module

from georisk.contexts.analysis.domain.entities import StageResult
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    ConfidenceTier,
    HazardType,
    Indicator,
    IndicatorSet,
    StageResultId,
    StageResultStatus,
    StageType,
)
from georisk.contexts.analysis.infrastructure.models import StageResultModel
from georisk.contexts.identity.domain.value_objects import TenantId


def _indicators_to_json(indicators: IndicatorSet) -> list[dict]:
    return [
        {"code": i.code, "value": i.value, "unit": i.unit, "sub_index": i.sub_index}
        for i in indicators.indicators
    ]


def _indicators_from_json(data: list[dict]) -> IndicatorSet:
    return IndicatorSet(
        indicators=tuple(
            Indicator(
                code=d["code"],
                value=d["value"],
                unit=d.get("unit", ""),
                sub_index=d.get("sub_index"),
            )
            for d in data
        )
    )


def _snapshot_to_json(snapshot: ComputationSnapshot) -> dict:
    return {"inputs": snapshot.inputs, "historical_count": snapshot.historical_count}


def _snapshot_from_json(data: dict) -> ComputationSnapshot:
    return ComputationSnapshot(
        inputs=data["inputs"], historical_count=data.get("historical_count", 0)
    )


def stage_result_to_domain(model: StageResultModel) -> StageResult:
    return StageResult(
        id=StageResultId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        assessment_id=str(model.assessment_id),
        hazard_type=HazardType(model.hazard_type),
        stage_type=StageType(model.stage_type),
        version=model.version,
        status=StageResultStatus(model.status),
        indicators=_indicators_from_json(model.indicators)
        if model.indicators is not None
        else None,
        confidence_tier=ConfidenceTier(model.confidence_tier) if model.confidence_tier else None,
        snapshot=_snapshot_from_json(model.snapshot),
        error=model.error,
        issued_by=model.issued_by,
        created_at=model.created_at,
        strategy_version=model.strategy_version,
        formula_version=model.formula_version,
        schema_version=model.schema_version,
    )


def apply_stage_result_to_model(entity: StageResult, model: StageResultModel) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.assessment_id = uuid_module.UUID(entity.assessment_id)
    model.hazard_type = entity.hazard_type.value
    model.stage_type = entity.stage_type.value
    model.version = entity.version
    model.status = entity.status.value
    model.indicators = (
        _indicators_to_json(entity.indicators) if entity.indicators is not None else None
    )
    model.confidence_tier = (
        entity.confidence_tier.value if entity.confidence_tier is not None else None
    )
    model.snapshot = _snapshot_to_json(entity.snapshot)
    model.error = entity.error
    model.issued_by = entity.issued_by
    model.created_at = entity.created_at
    model.strategy_version = entity.strategy_version
    model.formula_version = entity.formula_version
    model.schema_version = entity.schema_version
