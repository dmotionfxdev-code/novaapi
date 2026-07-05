"""Pydantic response models — independent of the SQLAlchemy models and
domain entities (Architecture Redesign §9). Same pattern as every prior
context. Read-only API: no request schemas — ``StageResult`` is never
created via this interface, only produced by the Workflow-Engine-triggered
``RecordStageResultCommand`` pipeline (composition root).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from georisk.contexts.analysis.domain.entities import StageResult


class IndicatorResponse(BaseModel):
    code: str
    value: float
    unit: str
    sub_index: str | None


class StageResultResponse(BaseModel):
    id: str
    tenant_id: str
    assessment_id: str
    hazard_type: str
    stage_type: str
    version: int
    status: str
    confidence_tier: str | None
    error: str | None
    issued_by: str
    created_at: datetime
    strategy_version: str | None
    formula_version: str | None
    indicators: list[IndicatorResponse]

    @classmethod
    def from_domain(cls, result: StageResult) -> StageResultResponse:
        return cls(
            id=str(result.id),
            tenant_id=str(result.tenant_id),
            assessment_id=result.assessment_id,
            hazard_type=result.hazard_type.value,
            stage_type=result.stage_type.value,
            version=result.version,
            status=result.status.value,
            confidence_tier=result.confidence_tier.value
            if result.confidence_tier is not None
            else None,
            error=result.error,
            issued_by=result.issued_by,
            created_at=result.created_at,
            strategy_version=result.strategy_version,
            formula_version=result.formula_version,
            indicators=(
                [
                    IndicatorResponse(
                        code=i.code, value=i.value, unit=i.unit, sub_index=i.sub_index
                    )
                    for i in result.indicators.indicators
                ]
                if result.indicators is not None
                else []
            ),
        )


class StageResultListResponse(BaseModel):
    data: list[StageResultResponse]

    @classmethod
    def from_domain(cls, results: list[StageResult]) -> StageResultListResponse:
        return cls(data=[StageResultResponse.from_domain(r) for r in results])
