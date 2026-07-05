"""Geospatial API (API Resource Model §20, adapted) — AOI and Sampling
Campaigns nested under ``/assessments/{assessment_id}/...`` purely as a
URL-path convenience; this router never imports anything from
``contexts.assessment`` (``assessment_id`` is handled as an opaque path
string throughout). Reuses ``ASSESSMENT_VIEW``/``ASSESSMENT_MANAGE`` —
same "no new permission codes, this is assessment-scoped evidence"
reasoning Sprint 5's Analysis Engine already established for
``StageResult``'s read API.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.geospatial.application.commands import (
    ConfigureSamplingCampaignCommand,
    DefineOrReviseAoiCommand,
    GenerateSamplePointsCommand,
)
from georisk.contexts.geospatial.application.handlers import (
    ConfigureSamplingCampaignHandler,
    DefineOrReviseAoiHandler,
    GenerateSamplePointsHandler,
)
from georisk.contexts.geospatial.application.queries import (
    GetActiveAoiQuery,
    GetSamplingCampaignQuery,
    ListAoiVersionsQuery,
    ListSamplingCampaignsQuery,
)
from georisk.contexts.geospatial.domain.value_objects import SamplingCampaignId
from georisk.contexts.geospatial.interface.schemas import (
    AoiListResponse,
    AoiResponse,
    ConfigureSamplingCampaignRequest,
    DefineOrReviseAoiRequest,
    SamplePointListResponse,
    SamplingCampaignListResponse,
    SamplingCampaignResponse,
)
from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.interface.dependencies import require_permission
from georisk.db.session import get_session

router = APIRouter(prefix="/assessments/{assessment_id}", tags=["geospatial"])


@router.get("/aoi", response_model=AoiResponse)
async def get_active_aoi(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AoiResponse:
    aoi = await GetActiveAoiQuery(session).handle(claims.tenant_id, assessment_id)
    return AoiResponse.from_domain(aoi)


@router.post("/aoi", response_model=AoiResponse, status_code=201)
async def define_or_revise_aoi(
    assessment_id: str,
    body: DefineOrReviseAoiRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AoiResponse:
    handler = DefineOrReviseAoiHandler(session)
    aoi = await handler.handle(
        DefineOrReviseAoiCommand(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            source=body.source,
            geojson=body.geometry,
            name=body.name,
            notes=body.notes,
            issued_by=str(claims.user_id),
        )
    )
    return AoiResponse.from_domain(aoi)


@router.get("/aoi/versions", response_model=AoiListResponse)
async def list_aoi_versions(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AoiListResponse:
    versions = await ListAoiVersionsQuery(session).handle(claims.tenant_id, assessment_id)
    return AoiListResponse.from_domain(versions)


@router.post(
    "/sampling-campaigns", response_model=SamplingCampaignResponse, status_code=201
)
async def configure_sampling_campaign(
    assessment_id: str,
    body: ConfigureSamplingCampaignRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SamplingCampaignResponse:
    handler = ConfigureSamplingCampaignHandler(session)
    campaign = await handler.handle(
        ConfigureSamplingCampaignCommand(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            aoi_id=body.aoi_id,
            name=body.name,
            method=body.method,
            sample_size=body.sample_size,
            strata=tuple({"label": s.label, "proportion": s.proportion} for s in body.strata),
            allocation_method=body.allocation_method,
            output_formats=tuple(body.output_formats),
            include_geometry=body.include_geometry,
            include_class_label=body.include_class_label,
            include_pixel_values=body.include_pixel_values,
            random_seed=body.random_seed,
            issued_by=str(claims.user_id),
        )
    )
    return SamplingCampaignResponse.from_domain(campaign)


@router.get("/sampling-campaigns", response_model=SamplingCampaignListResponse)
async def list_sampling_campaigns(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SamplingCampaignListResponse:
    campaigns = await ListSamplingCampaignsQuery(session).handle(claims.tenant_id, assessment_id)
    return SamplingCampaignListResponse.from_domain(campaigns)


@router.get(
    "/sampling-campaigns/{sampling_campaign_id}", response_model=SamplingCampaignResponse
)
async def get_sampling_campaign(
    assessment_id: str,
    sampling_campaign_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SamplingCampaignResponse:
    campaign = await GetSamplingCampaignQuery(session).handle(
        claims.tenant_id, SamplingCampaignId.from_string(sampling_campaign_id)
    )
    return SamplingCampaignResponse.from_domain(campaign)


@router.post(
    "/sampling-campaigns/{sampling_campaign_id}/actions/generate-points",
    response_model=SamplingCampaignResponse,
)
async def generate_sample_points(
    assessment_id: str,
    sampling_campaign_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SamplingCampaignResponse:
    handler = GenerateSamplePointsHandler(session)
    campaign = await handler.handle(
        GenerateSamplePointsCommand(
            tenant_id=str(claims.tenant_id),
            sampling_campaign_id=sampling_campaign_id,
            issued_by=str(claims.user_id),
        )
    )
    return SamplingCampaignResponse.from_domain(campaign)


@router.get(
    "/sampling-campaigns/{sampling_campaign_id}/points", response_model=SamplePointListResponse
)
async def list_sample_points(
    assessment_id: str,
    sampling_campaign_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SamplePointListResponse:
    campaign = await GetSamplingCampaignQuery(session).handle(
        claims.tenant_id, SamplingCampaignId.from_string(sampling_campaign_id)
    )
    return SamplePointListResponse.from_domain(campaign)
