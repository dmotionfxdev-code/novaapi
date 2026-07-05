"""Repository interfaces — domain layer contracts (Application Layer §1:
one repository per aggregate root). Concrete SQLAlchemy implementations
live in ``contexts/geospatial/infrastructure/repositories.py``.
"""

from __future__ import annotations

from typing import Protocol

from georisk.contexts.geospatial.domain.entities import AreaOfInterest, SamplingCampaign
from georisk.contexts.geospatial.domain.value_objects import AoiId, SamplingCampaignId
from georisk.contexts.identity.domain.value_objects import TenantId


class AreaOfInterestRepository(Protocol):
    async def get_by_id(self, aoi_id: AoiId) -> AreaOfInterest | None: ...

    async def get_active_for_assessment(
        self, tenant_id: TenantId, assessment_id: str
    ) -> AreaOfInterest | None: ...

    async def list_versions(
        self, tenant_id: TenantId, assessment_id: str
    ) -> list[AreaOfInterest]: ...

    async def save(self, aoi: AreaOfInterest) -> None: ...


class SamplingCampaignRepository(Protocol):
    async def get_by_id(self, campaign_id: SamplingCampaignId) -> SamplingCampaign | None: ...

    async def list_by_assessment(
        self, tenant_id: TenantId, assessment_id: str
    ) -> list[SamplingCampaign]: ...

    async def save(self, campaign: SamplingCampaign) -> None: ...
