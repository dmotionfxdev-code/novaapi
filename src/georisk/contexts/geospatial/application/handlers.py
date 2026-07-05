"""Command handlers for the Geospatial context — one transaction, one
aggregate per handler (Application Layer §9), same shape as every prior
context. Never imports from ``contexts.assessment`` or any other peer
context.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.geospatial.application.commands import (
    ConfigureSamplingCampaignCommand,
    DefineOrReviseAoiCommand,
    GenerateSamplePointsCommand,
)
from georisk.contexts.geospatial.domain.entities import AreaOfInterest, SamplingCampaign
from georisk.contexts.geospatial.domain.errors import (
    AoiNotFoundError,
    SamplingCampaignNotFoundError,
)
from georisk.contexts.geospatial.domain.events import AoiAttached, AoiRevised
from georisk.contexts.geospatial.domain.value_objects import (
    AllocationMethod,
    AoiId,
    AoiMetadata,
    AoiSource,
    Geometry,
    OutputFormat,
    SamplingCampaignId,
    SamplingMethod,
    SamplingStrategy,
    Stratum,
)
from georisk.contexts.geospatial.infrastructure.repositories import (
    SqlAlchemyAreaOfInterestRepository,
    SqlAlchemySamplingCampaignRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.db.outbox_writer import append_event


class DefineOrReviseAoiHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyAreaOfInterestRepository(session)

    async def handle(self, command: DefineOrReviseAoiCommand) -> AreaOfInterest:
        tenant_id = TenantId.from_string(command.tenant_id)
        geometry = Geometry(geojson=command.geojson)
        metadata = AoiMetadata(
            name=command.name, source=AoiSource(command.source), notes=command.notes
        )

        event: AoiAttached | AoiRevised
        existing = await self._repo.get_active_for_assessment(tenant_id, command.assessment_id)
        if existing is None:
            aoi, event = AreaOfInterest.define(
                tenant_id=tenant_id,
                assessment_id=command.assessment_id,
                geometry=geometry,
                metadata=metadata,
                created_by=command.issued_by,
            )
        else:
            aoi, event = AreaOfInterest.revise(
                previous=existing,
                geometry=geometry,
                metadata=metadata,
                created_by=command.issued_by,
            )
            existing.mark_superseded()
            await self._repo.save(existing)

        await self._repo.save(aoi)
        await append_event(
            self._session,
            aggregate_type="AreaOfInterest",
            aggregate_id=str(aoi.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return aoi


class ConfigureSamplingCampaignHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._aoi_repo = SqlAlchemyAreaOfInterestRepository(session)
        self._repo = SqlAlchemySamplingCampaignRepository(session)

    async def handle(self, command: ConfigureSamplingCampaignCommand) -> SamplingCampaign:
        tenant_id = TenantId.from_string(command.tenant_id)
        aoi_id = AoiId.from_string(command.aoi_id)
        aoi = await self._aoi_repo.get_by_id(aoi_id)
        if aoi is None or str(aoi.tenant_id) != str(tenant_id):
            raise AoiNotFoundError(f"AreaOfInterest {aoi_id} not found")

        strategy = SamplingStrategy(
            method=SamplingMethod(command.method),
            sample_size=command.sample_size,
            allocation_method=AllocationMethod(command.allocation_method),
            random_seed=command.random_seed,
            output_formats=frozenset(OutputFormat(fmt) for fmt in command.output_formats),
            include_geometry=command.include_geometry,
            include_class_label=command.include_class_label,
            include_pixel_values=command.include_pixel_values,
        )
        strata = tuple(
            Stratum(label=s["label"], proportion=s["proportion"]) for s in command.strata
        )

        campaign, event = SamplingCampaign.configure(
            tenant_id=tenant_id,
            assessment_id=command.assessment_id,
            aoi_id=aoi_id,
            name=command.name,
            strategy=strategy,
            strata=strata,
            created_by=command.issued_by,
        )
        await self._repo.save(campaign)
        await append_event(
            self._session,
            aggregate_type="SamplingCampaign",
            aggregate_id=str(campaign.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return campaign


class GenerateSamplePointsHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._aoi_repo = SqlAlchemyAreaOfInterestRepository(session)
        self._repo = SqlAlchemySamplingCampaignRepository(session)

    async def handle(self, command: GenerateSamplePointsCommand) -> SamplingCampaign:
        tenant_id = TenantId.from_string(command.tenant_id)
        campaign_id = SamplingCampaignId.from_string(command.sampling_campaign_id)
        campaign = await self._repo.get_by_id(campaign_id)
        if campaign is None or str(campaign.tenant_id) != str(tenant_id):
            raise SamplingCampaignNotFoundError(f"SamplingCampaign {campaign_id} not found")

        aoi = await self._aoi_repo.get_by_id(campaign.aoi_id)
        if aoi is None:
            raise AoiNotFoundError(f"AreaOfInterest {campaign.aoi_id} not found")

        event = campaign.generate_points(aoi_geometry=aoi.geometry)
        await self._repo.save(campaign)
        await append_event(
            self._session,
            aggregate_type="SamplingCampaign",
            aggregate_id=str(campaign.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return campaign
