"""Query handlers — read-only, never mutate, never go through the
command pipeline (Application Layer §3/§4). Same pattern as every prior
context.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.geospatial.domain.entities import AreaOfInterest, SamplingCampaign
from georisk.contexts.geospatial.domain.errors import (
    AoiNotFoundError,
    SamplingCampaignNotFoundError,
)
from georisk.contexts.geospatial.domain.value_objects import SamplingCampaignId
from georisk.contexts.geospatial.infrastructure.repositories import (
    SqlAlchemyAreaOfInterestRepository,
    SqlAlchemySamplingCampaignRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId


class GetActiveAoiQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, assessment_id: str) -> AreaOfInterest:
        aoi = await SqlAlchemyAreaOfInterestRepository(self._session).get_active_for_assessment(
            tenant_id, assessment_id
        )
        if aoi is None:
            raise AoiNotFoundError(f"No active AOI for assessment {assessment_id}")
        return aoi


class ListAoiVersionsQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, assessment_id: str) -> list[AreaOfInterest]:
        return await SqlAlchemyAreaOfInterestRepository(self._session).list_versions(
            tenant_id, assessment_id
        )


class GetSamplingCampaignQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(
        self, tenant_id: TenantId, sampling_campaign_id: SamplingCampaignId
    ) -> SamplingCampaign:
        campaign = await SqlAlchemySamplingCampaignRepository(self._session).get_by_id(
            sampling_campaign_id
        )
        if campaign is None or str(campaign.tenant_id) != str(tenant_id):
            raise SamplingCampaignNotFoundError(
                f"SamplingCampaign {sampling_campaign_id} not found"
            )
        return campaign


class ListSamplingCampaignsQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId, assessment_id: str) -> list[SamplingCampaign]:
        return await SqlAlchemySamplingCampaignRepository(self._session).list_by_assessment(
            tenant_id, assessment_id
        )
