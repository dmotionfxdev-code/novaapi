"""Reporting API — nested under ``/assessments/{assessment_id}/reports``
purely as a URL-path convenience (matching Analysis's/Prediction's
precedent), plus a tenant-level ``/dashboard/reports`` route for the
"Dashboard Projection Layer" (requirement #9). This router never imports
anything from ``contexts.assessment``, ``contexts.analysis``,
``contexts.prediction``, ``contexts.data_acquisition``, or
``contexts.validation``.

``get_assessment_reader``/``get_stage_result_reader``/
``get_prediction_reader``/``get_dataset_catalog_reader``/
``get_validation_reader`` depend only on Reporting's own Protocols
(``application/ports.py``) and read the concrete instances off
``request.app.state`` — constructed once, in ``api/app.py``'s lifespan.
This module never imports the concrete composition-root classes directly,
identical reasoning to ``contexts/prediction/interface/routes.py``'s
``get_variable_selection_reader`` docstring.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.interface.dependencies import require_permission
from georisk.contexts.reporting.application.commands import (
    FinalizeReportCommand,
    GenerateReportCommand,
)
from georisk.contexts.reporting.application.handlers import (
    FinalizeReportHandler,
    GenerateReportHandler,
)
from georisk.contexts.reporting.application.ports import (
    AssessmentReader,
    DatasetCatalogReader,
    PredictionReader,
    StageResultReader,
    ValidationReader,
)
from georisk.contexts.reporting.application.queries import (
    GetLatestReportQuery,
    GetReportQuery,
    ListDashboardProjectionsQuery,
    ListReportsByAssessmentQuery,
)
from georisk.contexts.reporting.domain.value_objects import ReportId
from georisk.contexts.reporting.interface.schemas import ReportListResponse, ReportResponse
from georisk.db.session import get_session

router = APIRouter(prefix="/assessments/{assessment_id}/reports", tags=["reporting"])
dashboard_router = APIRouter(prefix="/dashboard", tags=["reporting"])


def get_assessment_reader(request: Request) -> AssessmentReader:
    return request.app.state.reporting_assessment_reader


def get_stage_result_reader(request: Request) -> StageResultReader:
    return request.app.state.reporting_stage_result_reader


def get_prediction_reader(request: Request) -> PredictionReader:
    return request.app.state.reporting_prediction_reader


def get_dataset_catalog_reader(request: Request) -> DatasetCatalogReader:
    return request.app.state.reporting_dataset_catalog_reader


def get_validation_reader(request: Request) -> ValidationReader:
    return request.app.state.reporting_validation_reader


@router.get("", response_model=ReportListResponse)
async def list_reports(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReportListResponse:
    reports = await ListReportsByAssessmentQuery(session).handle(claims.tenant_id, assessment_id)
    return ReportListResponse.from_domain(reports)


@router.get("/latest", response_model=ReportResponse)
async def get_latest_report(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReportResponse:
    report = await GetLatestReportQuery(session).handle(claims.tenant_id, assessment_id)
    return ReportResponse.from_domain(report)


@router.get("/{report_id}", response_model=ReportResponse)
async def get_report(
    assessment_id: str,
    report_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReportResponse:
    report = await GetReportQuery(session).handle(
        claims.tenant_id, ReportId.from_string(report_id)
    )
    return ReportResponse.from_domain(report)


@router.post("/actions/generate", response_model=ReportResponse, status_code=201)
async def generate_report(
    assessment_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
    assessment_reader: Annotated[AssessmentReader, Depends(get_assessment_reader)],
    stage_result_reader: Annotated[StageResultReader, Depends(get_stage_result_reader)],
    prediction_reader: Annotated[PredictionReader, Depends(get_prediction_reader)],
    dataset_catalog_reader: Annotated[DatasetCatalogReader, Depends(get_dataset_catalog_reader)],
    validation_reader: Annotated[ValidationReader, Depends(get_validation_reader)],
) -> ReportResponse:
    handler = GenerateReportHandler(
        session,
        assessment_reader,
        stage_result_reader,
        prediction_reader,
        dataset_catalog_reader,
        validation_reader,
    )
    report = await handler.handle(
        GenerateReportCommand(
            tenant_id=str(claims.tenant_id),
            assessment_id=assessment_id,
            issued_by=str(claims.user_id),
        )
    )
    return ReportResponse.from_domain(report)


@router.post("/{report_id}/actions/finalize", response_model=ReportResponse)
async def finalize_report(
    assessment_id: str,
    report_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_MANAGE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReportResponse:
    handler = FinalizeReportHandler(session)
    report = await handler.handle(
        FinalizeReportCommand(
            tenant_id=str(claims.tenant_id),
            report_id=report_id,
            finalized_by=str(claims.user_id),
        )
    )
    return ReportResponse.from_domain(report)


@dashboard_router.get("/reports", response_model=ReportListResponse)
async def list_dashboard_reports(
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.ASSESSMENT_VIEW))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ReportListResponse:
    reports = await ListDashboardProjectionsQuery(session).handle(claims.tenant_id)
    return ReportListResponse.from_domain(reports)
