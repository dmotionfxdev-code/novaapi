"""Prediction API — nested under ``/assessments/{assessment_id}/predictions``
purely as a URL-path convenience (matching Analysis's/Geospatial's
precedent); this router never imports anything from
``contexts.data_acquisition`` or ``contexts.geospatial``. Reuses
``ASSESSMENT_VIEW``/``ASSESSMENT_MANAGE`` — same "no new permission
codes, this is assessment-scoped evidence" reasoning Sprint 5/7 already
established.

``get_variable_selection_reader``/``get_sampling_campaign_reader``/
``get_prediction_data_provider`` depend only on Prediction's own
Protocols (``application/ports.py``) and read the concrete instances off
``request.app.state`` — constructed once, in ``api/app.py``'s lifespan.
This module never imports the concrete composition-root classes
directly, which would give ``contexts.prediction`` a transitive import
path into ``contexts.data_acquisition``/``contexts.geospatial`` and
violate the import-linter's peer-independence contract — the identical
reasoning ``contexts/assessment/interface/routes.py``'s
``get_stage_executor`` docstring already documents for
``StageExecutor``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.interface.dependencies import require_permission
from georisk.contexts.prediction.application.commands import RunPredictionCommand
from georisk.contexts.prediction.application.handlers import RunPredictionHandler
from georisk.contexts.prediction.application.ports import (
    PredictionDataProvider,
    SamplingCampaignReader,
    VariableSelectionReader,
)
from georisk.contexts.prediction.application.queries import (
    GetPredictionRunQuery,
    ListPredictionRunsQuery,
)
from georisk.contexts.prediction.domain.value_objects import PredictionRunId
from georisk.contexts.prediction.interface.schemas import (
    PredictionRunListResponse,
    PredictionRunResponse,
    RunPredictionRequest,
)
from georisk.db.session import get_session

router = APIRouter(prefix="/assessments/{assessment_id}/predictions", tags=["prediction"])


def get_variable_selection_reader(request: Request) -> VariableSelectionReader:
    return request.app.state.prediction_variable_selection_reader


def get_sampling_campaign_reader(request: Request) -> SamplingCampaignReader:
    return request.app.state.prediction_sampling_campaign_reader


def get_prediction_data_provider(request: Request) -> PredictionDataProvider:
    return request.app.state.prediction_data_provider


@router.get("", response_model=PredictionRunListResponse)
async def list_prediction_runs(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PredictionRunListResponse:
    runs = await ListPredictionRunsQuery(session).handle(claims.tenant_id, assessment_id)
    return PredictionRunListResponse.from_domain(runs)


@router.get("/{prediction_run_id}", response_model=PredictionRunResponse)
async def get_prediction_run(
    assessment_id: str,
    prediction_run_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PredictionRunResponse:
    run = await GetPredictionRunQuery(session).handle(
        claims.tenant_id, PredictionRunId.from_string(prediction_run_id)
    )
    return PredictionRunResponse.from_domain(run)


@router.post("/actions/run", response_model=PredictionRunResponse, status_code=201)
async def run_prediction(
    assessment_id: str,
    body: RunPredictionRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
    variable_selection_reader: Annotated[
        VariableSelectionReader, Depends(get_variable_selection_reader)
    ],
    sampling_campaign_reader: Annotated[
        SamplingCampaignReader, Depends(get_sampling_campaign_reader)
    ],
    data_provider: Annotated[PredictionDataProvider, Depends(get_prediction_data_provider)],
) -> PredictionRunResponse:
    handler = RunPredictionHandler(
        session, variable_selection_reader, sampling_campaign_reader, data_provider
    )
    run = await handler.handle(
        RunPredictionCommand(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            variable_selection_id=body.variable_selection_id,
            sampling_campaign_id=body.sampling_campaign_id,
            method=body.method,
            issued_by=str(claims.user_id),
        )
    )
    return PredictionRunResponse.from_domain(run)
