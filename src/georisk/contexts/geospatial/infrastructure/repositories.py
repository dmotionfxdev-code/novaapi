"""Concrete SQLAlchemy repositories implementing
``contexts/geospatial/domain/repositories.py``'s Protocols. AOI is
write-once-per-version (Domain Model §1 row 3: "edits create a new
version, never mutate in place") — ``save`` always inserts a new row for
a new ``AreaOfInterest`` instance; the one exception is ``mark_superseded``
flipping a *previous* version's status, saved via the same method (an
``UPDATE`` on an existing row, not a new version).
"""

from __future__ import annotations

import uuid as uuid_module

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.geospatial.domain.entities import AreaOfInterest, SamplingCampaign
from georisk.contexts.geospatial.domain.value_objects import (
    AoiId,
    AoiStatus,
    SamplingCampaignId,
)
from georisk.contexts.geospatial.infrastructure import mappers
from georisk.contexts.geospatial.infrastructure.models import (
    AreaOfInterestModel,
    SamplingCampaignModel,
)
from georisk.contexts.identity.domain.value_objects import TenantId


class SqlAlchemyAreaOfInterestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, aoi_id: AoiId) -> AreaOfInterest | None:
        model = await self._session.get(AreaOfInterestModel, aoi_id.value)
        return mappers.aoi_to_domain(model) if model else None

    async def get_active_for_assessment(
        self, tenant_id: TenantId, assessment_id: str
    ) -> AreaOfInterest | None:
        query = select(AreaOfInterestModel).where(
            AreaOfInterestModel.tenant_id == tenant_id.value,
            AreaOfInterestModel.assessment_id == uuid_module.UUID(assessment_id),
            AreaOfInterestModel.status == AoiStatus.ACTIVE.value,
        )
        result = await self._session.execute(query)
        model = result.scalar_one_or_none()
        return mappers.aoi_to_domain(model) if model else None

    async def list_versions(
        self, tenant_id: TenantId, assessment_id: str
    ) -> list[AreaOfInterest]:
        query = (
            select(AreaOfInterestModel)
            .where(
                AreaOfInterestModel.tenant_id == tenant_id.value,
                AreaOfInterestModel.assessment_id == uuid_module.UUID(assessment_id),
            )
            .order_by(AreaOfInterestModel.version)
        )
        result = await self._session.execute(query)
        return [mappers.aoi_to_domain(m) for m in result.scalars().all()]

    async def save(self, aoi: AreaOfInterest) -> None:
        model = await self._session.get(AreaOfInterestModel, aoi.id.value)
        if model is None:
            model = AreaOfInterestModel()
            self._session.add(model)
        mappers.apply_aoi_to_model(aoi, model)


class SqlAlchemySamplingCampaignRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, campaign_id: SamplingCampaignId) -> SamplingCampaign | None:
        model = await self._session.get(SamplingCampaignModel, campaign_id.value)
        return mappers.sampling_campaign_to_domain(model) if model else None

    async def list_by_assessment(
        self, tenant_id: TenantId, assessment_id: str
    ) -> list[SamplingCampaign]:
        query = (
            select(SamplingCampaignModel)
            .where(
                SamplingCampaignModel.tenant_id == tenant_id.value,
                SamplingCampaignModel.assessment_id == uuid_module.UUID(assessment_id),
            )
            .order_by(SamplingCampaignModel.created_at)
        )
        result = await self._session.execute(query)
        return [mappers.sampling_campaign_to_domain(m) for m in result.scalars().all()]

    async def save(self, campaign: SamplingCampaign) -> None:
        model = await self._session.get(SamplingCampaignModel, campaign.id.value)
        if model is None:
            model = SamplingCampaignModel()
            self._session.add(model)
        mappers.apply_sampling_campaign_to_model(campaign, model)
