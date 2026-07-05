"""Dashboard & Visualization API. Every route here is a GET — Sprint 12's
"Use projection/read-model approach only" made structural at the
interface layer too, not just in the domain/application layers. Nested
under ``/dashboards`` (plural — deliberately distinct from Reporting's
own pre-existing ``/dashboard/reports`` route from Sprint 9, so the two
never collide and a reader can immediately tell which context a given
path belongs to). This router never imports anything from
``contexts.assessment``, ``contexts.analysis``, ``contexts.prediction``,
``contexts.validation``, ``contexts.reporting``, ``contexts.notification``,
or ``contexts.data_acquisition``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from georisk.contexts.dashboard.application.ports import (
    AssessmentReader,
    DatasetReader,
    NotificationReader,
    PredictionReader,
    ReportReader,
    StageResultReader,
    ValidationReader,
)
from georisk.contexts.dashboard.application.queries import (
    GetAlertDashboardQuery,
    GetAssessmentWorkspaceQuery,
    GetDatasetDashboardQuery,
    GetExecutiveDashboardQuery,
    GetHazardDashboardQuery,
    GetPredictionDashboardQuery,
    GetValidationDashboardQuery,
)
from georisk.contexts.dashboard.interface.schemas import (
    AlertDashboardResponse,
    AssessmentWorkspaceResponse,
    DatasetDashboardResponse,
    ExecutiveDashboardResponse,
    HazardDashboardResponse,
    PredictionDashboardResponse,
    ValidationDashboardResponse,
)
from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.interface.dependencies import require_permission

router = APIRouter(prefix="/dashboards", tags=["dashboard"])

_ViewClaims = Annotated[
    AccessTokenClaims, Depends(require_permission(PermissionCode.DASHBOARD_VIEW))
]


def _assessment_reader(request: Request) -> AssessmentReader:
    return request.app.state.dashboard_assessment_reader


def _stage_result_reader(request: Request) -> StageResultReader:
    return request.app.state.dashboard_stage_result_reader


def _prediction_reader(request: Request) -> PredictionReader:
    return request.app.state.dashboard_prediction_reader


def _validation_reader(request: Request) -> ValidationReader:
    return request.app.state.dashboard_validation_reader


def _notification_reader(request: Request) -> NotificationReader:
    return request.app.state.dashboard_notification_reader


def _dataset_reader(request: Request) -> DatasetReader:
    return request.app.state.dashboard_dataset_reader


def _report_reader(request: Request) -> ReportReader:
    return request.app.state.dashboard_report_reader


@router.get("/workspace/{assessment_id}", response_model=AssessmentWorkspaceResponse)
async def get_assessment_workspace(
    assessment_id: str,
    claims: _ViewClaims,
    assessment_reader: Annotated[AssessmentReader, Depends(_assessment_reader)],
    stage_result_reader: Annotated[StageResultReader, Depends(_stage_result_reader)],
    prediction_reader: Annotated[PredictionReader, Depends(_prediction_reader)],
    validation_reader: Annotated[ValidationReader, Depends(_validation_reader)],
    report_reader: Annotated[ReportReader, Depends(_report_reader)],
    notification_reader: Annotated[NotificationReader, Depends(_notification_reader)],
) -> AssessmentWorkspaceResponse:
    query = GetAssessmentWorkspaceQuery(
        assessment_reader,
        stage_result_reader,
        prediction_reader,
        validation_reader,
        report_reader,
        notification_reader,
    )
    projection = await query.handle(tenant_id=str(claims.tenant_id), assessment_id=assessment_id)
    return AssessmentWorkspaceResponse.from_domain(projection)


@router.get("/executive", response_model=ExecutiveDashboardResponse)
async def get_executive_dashboard(
    claims: _ViewClaims,
    assessment_reader: Annotated[AssessmentReader, Depends(_assessment_reader)],
    notification_reader: Annotated[NotificationReader, Depends(_notification_reader)],
    report_reader: Annotated[ReportReader, Depends(_report_reader)],
) -> ExecutiveDashboardResponse:
    query = GetExecutiveDashboardQuery(assessment_reader, notification_reader, report_reader)
    dashboard = await query.handle(tenant_id=str(claims.tenant_id))
    return ExecutiveDashboardResponse.from_domain(dashboard)


@router.get("/firas", response_model=HazardDashboardResponse)
async def get_firas_dashboard(
    claims: _ViewClaims,
    assessment_reader: Annotated[AssessmentReader, Depends(_assessment_reader)],
    stage_result_reader: Annotated[StageResultReader, Depends(_stage_result_reader)],
) -> HazardDashboardResponse:
    query = GetHazardDashboardQuery(assessment_reader, stage_result_reader)
    dashboard = await query.handle(tenant_id=str(claims.tenant_id), hazard_type="FLOOD")
    return HazardDashboardResponse.from_domain(dashboard)


@router.get("/wrras", response_model=HazardDashboardResponse)
async def get_wrras_dashboard(
    claims: _ViewClaims,
    assessment_reader: Annotated[AssessmentReader, Depends(_assessment_reader)],
    stage_result_reader: Annotated[StageResultReader, Depends(_stage_result_reader)],
) -> HazardDashboardResponse:
    query = GetHazardDashboardQuery(assessment_reader, stage_result_reader)
    dashboard = await query.handle(tenant_id=str(claims.tenant_id), hazard_type="WILDFIRE")
    return HazardDashboardResponse.from_domain(dashboard)


@router.get("/prediction", response_model=PredictionDashboardResponse)
async def get_prediction_dashboard(
    claims: _ViewClaims,
    assessment_reader: Annotated[AssessmentReader, Depends(_assessment_reader)],
    prediction_reader: Annotated[PredictionReader, Depends(_prediction_reader)],
) -> PredictionDashboardResponse:
    query = GetPredictionDashboardQuery(assessment_reader, prediction_reader)
    dashboard = await query.handle(tenant_id=str(claims.tenant_id))
    return PredictionDashboardResponse.from_domain(dashboard)


@router.get("/validation", response_model=ValidationDashboardResponse)
async def get_validation_dashboard(
    claims: _ViewClaims,
    assessment_reader: Annotated[AssessmentReader, Depends(_assessment_reader)],
    validation_reader: Annotated[ValidationReader, Depends(_validation_reader)],
) -> ValidationDashboardResponse:
    query = GetValidationDashboardQuery(assessment_reader, validation_reader)
    dashboard = await query.handle(tenant_id=str(claims.tenant_id))
    return ValidationDashboardResponse.from_domain(dashboard)


@router.get("/alerts", response_model=AlertDashboardResponse)
async def get_alert_dashboard(
    claims: _ViewClaims,
    notification_reader: Annotated[NotificationReader, Depends(_notification_reader)],
) -> AlertDashboardResponse:
    query = GetAlertDashboardQuery(notification_reader)
    dashboard = await query.handle(tenant_id=str(claims.tenant_id))
    return AlertDashboardResponse.from_domain(dashboard)


@router.get("/datasets", response_model=DatasetDashboardResponse)
async def get_dataset_dashboard(
    claims: _ViewClaims,
    dataset_reader: Annotated[DatasetReader, Depends(_dataset_reader)],
) -> DatasetDashboardResponse:
    query = GetDatasetDashboardQuery(dataset_reader)
    dashboard = await query.handle(tenant_id=str(claims.tenant_id))
    return DatasetDashboardResponse.from_domain(dashboard)
