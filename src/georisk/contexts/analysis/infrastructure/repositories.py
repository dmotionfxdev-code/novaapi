"""Concrete SQLAlchemy repository implementing
``contexts/analysis/domain/repositories.StageResultRepository``. Write-once
per version — ``save`` always inserts a new row (Domain Model §1 row 11:
"Immutable once COMPLETE ... a re-run creates a new version, never
overwrites").
"""

from __future__ import annotations

import uuid as uuid_module

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.analysis.domain.entities import RiskLayer, StageResult
from georisk.contexts.analysis.domain.value_objects import (
    HazardType,
    RiskLayerId,
    StageResultId,
    StageResultStatus,
    StageType,
)
from georisk.contexts.analysis.infrastructure import mappers
from georisk.contexts.analysis.infrastructure.models import RiskLayerModel, StageResultModel
from georisk.contexts.identity.domain.value_objects import TenantId


class SqlAlchemyStageResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, stage_result_id: StageResultId) -> StageResult | None:
        model = await self._session.get(StageResultModel, stage_result_id.value)
        return mappers.stage_result_to_domain(model) if model else None

    async def get_latest(
        self, tenant_id: TenantId, assessment_id: str, stage_type: StageType
    ) -> StageResult | None:
        query = (
            select(StageResultModel)
            .where(
                StageResultModel.tenant_id == tenant_id.value,
                StageResultModel.assessment_id == uuid_module.UUID(assessment_id),
                StageResultModel.stage_type == stage_type.value,
                StageResultModel.status == StageResultStatus.COMPLETE.value,
            )
            .order_by(StageResultModel.version.desc())
            .limit(1)
        )
        result = await self._session.execute(query)
        model = result.scalar_one_or_none()
        return mappers.stage_result_to_domain(model) if model else None

    async def list_by_assessment(
        self, tenant_id: TenantId, assessment_id: str
    ) -> list[StageResult]:
        query = (
            select(StageResultModel)
            .where(
                StageResultModel.tenant_id == tenant_id.value,
                StageResultModel.assessment_id == uuid_module.UUID(assessment_id),
            )
            .order_by(StageResultModel.stage_type, StageResultModel.version)
        )
        result = await self._session.execute(query)
        return [mappers.stage_result_to_domain(m) for m in result.scalars().all()]

    async def list_historical_indicators(
        self,
        tenant_id: TenantId,
        hazard_type: HazardType,
        stage_type: StageType,
        *,
        exclude_assessment_id: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        query = (
            select(StageResultModel)
            .where(
                StageResultModel.tenant_id == tenant_id.value,
                StageResultModel.hazard_type == hazard_type.value,
                StageResultModel.stage_type == stage_type.value,
                StageResultModel.status == StageResultStatus.COMPLETE.value,
            )
            .order_by(StageResultModel.created_at.desc())
            .limit(limit)
        )
        if exclude_assessment_id is not None:
            query = query.where(
                StageResultModel.assessment_id != uuid_module.UUID(exclude_assessment_id)
            )

        result = await self._session.execute(query)
        return [m.snapshot["inputs"] for m in result.scalars().all()]

    async def list_all_indicators_by_assessment(
        self, tenant_id: TenantId, hazard_type: HazardType, *, limit: int = 200
    ) -> list[dict]:
        query = (
            select(StageResultModel)
            .where(
                StageResultModel.tenant_id == tenant_id.value,
                StageResultModel.hazard_type == hazard_type.value,
                StageResultModel.status == StageResultStatus.COMPLETE.value,
            )
            .order_by(
                StageResultModel.assessment_id,
                StageResultModel.stage_type,
                StageResultModel.version,
            )
        )
        result = await self._session.execute(query)
        # Grouped in Python, not SQL: merging every COMPLETE stage's
        # ``snapshot["inputs"]`` into one row per assessment_id. Ascending
        # version order means a later re-run of the same stage overwrites
        # an earlier one via ``dict.update`` — "latest version wins",
        # mirroring ``get_latest``'s own ordering intent.
        merged: dict[uuid_module.UUID, dict] = {}
        for model in result.scalars().all():
            merged.setdefault(model.assessment_id, {}).update(model.snapshot["inputs"])
        return list(merged.values())[:limit]

    async def next_version(
        self, tenant_id: TenantId, assessment_id: str, stage_type: StageType
    ) -> int:
        query = select(func.coalesce(func.max(StageResultModel.version), 0) + 1).where(
            StageResultModel.tenant_id == tenant_id.value,
            StageResultModel.assessment_id == uuid_module.UUID(assessment_id),
            StageResultModel.stage_type == stage_type.value,
        )
        result = await self._session.scalar(query)
        assert result is not None  # coalesce(..., 0) + 1 always yields a value
        return result

    async def save(self, stage_result: StageResult) -> None:
        model = StageResultModel()
        mappers.apply_stage_result_to_model(stage_result, model)
        self._session.add(model)


class SqlAlchemyRiskLayerRepository:
    """Sprint C — insert-only, "latest version wins" repository for
    ``RiskLayer``, mirroring ``SqlAlchemyStageResultRepository`` exactly.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, risk_layer_id: RiskLayerId) -> RiskLayer | None:
        model = await self._session.get(RiskLayerModel, risk_layer_id.value)
        return mappers.risk_layer_to_domain(model) if model else None

    async def get_latest(
        self, tenant_id: TenantId, assessment_id: str, stage_type: StageType
    ) -> RiskLayer | None:
        query = (
            select(RiskLayerModel)
            .where(
                RiskLayerModel.tenant_id == tenant_id.value,
                RiskLayerModel.assessment_id == uuid_module.UUID(assessment_id),
                RiskLayerModel.stage_type == stage_type.value,
            )
            .order_by(RiskLayerModel.version.desc())
            .limit(1)
        )
        result = await self._session.execute(query)
        model = result.scalar_one_or_none()
        return mappers.risk_layer_to_domain(model) if model else None

    async def next_version(
        self, tenant_id: TenantId, assessment_id: str, stage_type: StageType
    ) -> int:
        query = select(func.coalesce(func.max(RiskLayerModel.version), 0) + 1).where(
            RiskLayerModel.tenant_id == tenant_id.value,
            RiskLayerModel.assessment_id == uuid_module.UUID(assessment_id),
            RiskLayerModel.stage_type == stage_type.value,
        )
        result = await self._session.scalar(query)
        assert result is not None  # coalesce(..., 0) + 1 always yields a value
        return result

    async def save(self, risk_layer: RiskLayer) -> None:
        model = RiskLayerModel()
        mappers.apply_risk_layer_to_model(risk_layer, model)
        self._session.add(model)
