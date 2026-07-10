"""StageResult read API — nested under
``/assessments/{assessment_id}/stage-results`` purely as a URL-path
convenience; this router never imports anything from
``contexts.assessment`` (``assessment_id`` is handled as an opaque path
string throughout, exactly like Validation's router in Sprint 4).
Read-only: a ``StageResult`` is produced only by the Workflow-Engine
-triggered ``RecordStageResultCommand`` pipeline (composition root), never
via this API. Permission reuses ``assessment:view`` — a ``StageResult`` is
read-only evidence about an assessment a caller can already see.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.analysis.application.queries import (
    GetLatestRiskLayerQuery,
    GetLatestStageResultQuery,
    ListStageResultsQuery,
)
from georisk.contexts.analysis.domain.errors import StageResultNotFoundError
from georisk.contexts.analysis.domain.value_objects import StageType
from georisk.contexts.analysis.interface.schemas import (
    RiskLayerResponse,
    RiskSummaryResponse,
    StageResultListResponse,
    StageResultResponse,
)
from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.interface.dependencies import require_permission
from georisk.db.session import get_session

router = APIRouter(prefix="/assessments/{assessment_id}/stage-results", tags=["stage-results"])

# Sprint C — read-only spatial-output routes (requirement #5). Separate
# router (same "assessment_id opaque path string" convention, same
# assessment:view permission) since its URL shape
# (/assessments/{id}/risk-layer[.geojson], /assessments/{id}/risk-summary)
# doesn't nest under /stage-results.
risk_layer_router = APIRouter(prefix="/assessments/{assessment_id}", tags=["risk-layer"])


@router.get("", response_model=StageResultListResponse)
async def list_stage_results(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StageResultListResponse:
    query = ListStageResultsQuery(session)
    results = await query.handle(claims.tenant_id, assessment_id)
    return StageResultListResponse.from_domain(results)


@router.get("/{stage_type}", response_model=StageResultResponse)
async def get_latest_stage_result(
    assessment_id: str,
    stage_type: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StageResultResponse:
    query = GetLatestStageResultQuery(session)
    try:
        result = await query.handle(claims.tenant_id, assessment_id, StageType(stage_type))
    except ValueError as exc:
        raise StageResultNotFoundError(f"Unknown stage type {stage_type!r}") from exc
    return StageResultResponse.from_domain(result)


@risk_layer_router.get("/risk-layer", response_model=RiskLayerResponse)
async def get_risk_layer(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RiskLayerResponse:
    """Metadata only — id/counts/bbox/CRS/risk facts, never the full
    ``FeatureCollection`` body (see ``/risk-layer.geojson`` for that).
    Reads whatever was already generated (requirement #6: never
    regenerates on request)."""
    layer = await GetLatestRiskLayerQuery(session).handle(claims.tenant_id, assessment_id)
    return RiskLayerResponse.from_domain(layer)


@risk_layer_router.get("/risk-layer.geojson")
async def get_risk_layer_geojson(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Requirement #5/#7: the raw RFC 7946 ``FeatureCollection`` — a bare
    ``Response`` (not a Pydantic ``response_model``, which would mean
    decoding then re-encoding an already-JSON JSONB value) with
    ``application/geo+json``, directly loadable in Leaflet/MapLibre
    GL/OpenLayers/QGIS with zero client-side unwrapping."""
    layer = await GetLatestRiskLayerQuery(session).handle(claims.tenant_id, assessment_id)
    return Response(content=json.dumps(layer.geojson), media_type="application/geo+json")


@risk_layer_router.get("/risk-summary", response_model=RiskSummaryResponse)
async def get_risk_summary(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RiskSummaryResponse:
    """The non-spatial companion — just the computed-risk facts, no
    geometry at all, for a client that only needs the number/level."""
    layer = await GetLatestRiskLayerQuery(session).handle(claims.tenant_id, assessment_id)
    return RiskSummaryResponse.from_domain(layer)
