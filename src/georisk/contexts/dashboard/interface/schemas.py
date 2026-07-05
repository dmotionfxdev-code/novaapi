"""Pydantic response models — independent of the domain value objects
(Architecture Redesign §9). Same pattern as every prior context. No
request models beyond path/query parameters — every route in this
context is a GET.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from georisk.contexts.dashboard.domain.value_objects import (
    AlertDashboard,
    AssessmentWorkspaceProjection,
    DatasetDashboard,
    ExecutiveDashboard,
    HazardDashboard,
    KpiWidget,
    NotificationSummaryCard,
    PredictionDashboard,
    ReportSummaryCard,
    StageResultSummaryCard,
    SummaryCard,
    TrendPoint,
    ValidationDashboard,
)


class KpiWidgetResponse(BaseModel):
    label: str
    value: float
    unit: str

    @classmethod
    def from_domain(cls, widget: KpiWidget) -> KpiWidgetResponse:
        return cls(label=widget.label, value=widget.value, unit=widget.unit)


class SummaryCardResponse(BaseModel):
    label: str
    count: int
    breakdown: dict[str, int]

    @classmethod
    def from_domain(cls, card: SummaryCard) -> SummaryCardResponse:
        return cls(label=card.label, count=card.count, breakdown=card.breakdown)


class TrendPointResponse(BaseModel):
    label: str
    value: float
    occurred_at: datetime

    @classmethod
    def from_domain(cls, point: TrendPoint) -> TrendPointResponse:
        return cls(label=point.label, value=point.value, occurred_at=point.occurred_at)


class StageResultSummaryCardResponse(BaseModel):
    stage_type: str
    status: str
    confidence_tier: str | None
    primary_indicators: dict[str, float]
    computed_at: datetime

    @classmethod
    def from_domain(cls, card: StageResultSummaryCard) -> StageResultSummaryCardResponse:
        return cls(
            stage_type=card.stage_type,
            status=card.status,
            confidence_tier=card.confidence_tier,
            primary_indicators=card.primary_indicators,
            computed_at=card.computed_at,
        )


class AssessmentWorkspaceResponse(BaseModel):
    assessment_id: str
    name: str
    hazard_type: str
    status: str
    stage_results: list[StageResultSummaryCardResponse]
    latest_prediction_method: str | None
    latest_prediction_summary: str | None
    latest_validation_verdict: str | None
    latest_validation_mode: str | None
    latest_report_version: int | None
    latest_report_status: str | None
    active_notification_count: int
    generated_at: datetime

    @classmethod
    def from_domain(cls, projection: AssessmentWorkspaceProjection) -> AssessmentWorkspaceResponse:
        return cls(
            assessment_id=projection.assessment_id,
            name=projection.name,
            hazard_type=projection.hazard_type,
            status=projection.status,
            stage_results=[
                StageResultSummaryCardResponse.from_domain(s) for s in projection.stage_results
            ],
            latest_prediction_method=projection.latest_prediction_method,
            latest_prediction_summary=projection.latest_prediction_summary,
            latest_validation_verdict=projection.latest_validation_verdict,
            latest_validation_mode=projection.latest_validation_mode,
            latest_report_version=projection.latest_report_version,
            latest_report_status=projection.latest_report_status,
            active_notification_count=projection.active_notification_count,
            generated_at=projection.generated_at,
        )


class ReportSummaryCardResponse(BaseModel):
    assessment_id: str
    assessment_name: str
    report_version: int
    status: str
    generated_at: datetime

    @classmethod
    def from_domain(cls, card: ReportSummaryCard) -> ReportSummaryCardResponse:
        return cls(
            assessment_id=card.assessment_id,
            assessment_name=card.assessment_name,
            report_version=card.report_version,
            status=card.status,
            generated_at=card.generated_at,
        )


class ExecutiveDashboardResponse(BaseModel):
    tenant_id: str
    total_assessments: int
    assessments_by_status: dict[str, int]
    assessments_by_hazard_type: dict[str, int]
    kpis: list[KpiWidgetResponse]
    summary_cards: list[SummaryCardResponse]
    recent_reports: list[ReportSummaryCardResponse]
    generated_at: datetime

    @classmethod
    def from_domain(cls, dashboard: ExecutiveDashboard) -> ExecutiveDashboardResponse:
        return cls(
            tenant_id=dashboard.tenant_id,
            total_assessments=dashboard.total_assessments,
            assessments_by_status=dashboard.assessments_by_status,
            assessments_by_hazard_type=dashboard.assessments_by_hazard_type,
            kpis=[KpiWidgetResponse.from_domain(k) for k in dashboard.kpis],
            summary_cards=[SummaryCardResponse.from_domain(s) for s in dashboard.summary_cards],
            recent_reports=[
                ReportSummaryCardResponse.from_domain(r) for r in dashboard.recent_reports
            ],
            generated_at=dashboard.generated_at,
        )


class HazardDashboardResponse(BaseModel):
    hazard_type: str
    total_assessments: int
    kpis: list[KpiWidgetResponse]
    summary_cards: list[SummaryCardResponse]
    trend: list[TrendPointResponse]
    generated_at: datetime

    @classmethod
    def from_domain(cls, dashboard: HazardDashboard) -> HazardDashboardResponse:
        return cls(
            hazard_type=dashboard.hazard_type,
            total_assessments=dashboard.total_assessments,
            kpis=[KpiWidgetResponse.from_domain(k) for k in dashboard.kpis],
            summary_cards=[SummaryCardResponse.from_domain(s) for s in dashboard.summary_cards],
            trend=[TrendPointResponse.from_domain(t) for t in dashboard.trend],
            generated_at=dashboard.generated_at,
        )


class PredictionDashboardResponse(BaseModel):
    total_prediction_runs: int
    runs_by_method: dict[str, int]
    kpis: list[KpiWidgetResponse]
    trend: list[TrendPointResponse]
    generated_at: datetime

    @classmethod
    def from_domain(cls, dashboard: PredictionDashboard) -> PredictionDashboardResponse:
        return cls(
            total_prediction_runs=dashboard.total_prediction_runs,
            runs_by_method=dashboard.runs_by_method,
            kpis=[KpiWidgetResponse.from_domain(k) for k in dashboard.kpis],
            trend=[TrendPointResponse.from_domain(t) for t in dashboard.trend],
            generated_at=dashboard.generated_at,
        )


class ValidationDashboardResponse(BaseModel):
    total_validation_runs: int
    runs_by_mode: dict[str, int]
    pass_count: int
    fail_count: int
    kpis: list[KpiWidgetResponse]
    trend: list[TrendPointResponse]
    generated_at: datetime

    @classmethod
    def from_domain(cls, dashboard: ValidationDashboard) -> ValidationDashboardResponse:
        return cls(
            total_validation_runs=dashboard.total_validation_runs,
            runs_by_mode=dashboard.runs_by_mode,
            pass_count=dashboard.pass_count,
            fail_count=dashboard.fail_count,
            kpis=[KpiWidgetResponse.from_domain(k) for k in dashboard.kpis],
            trend=[TrendPointResponse.from_domain(t) for t in dashboard.trend],
            generated_at=dashboard.generated_at,
        )


class NotificationSummaryCardResponse(BaseModel):
    notification_id: str
    assessment_id: str
    severity: str
    status: str
    metric_code: str
    message: str
    created_at: datetime

    @classmethod
    def from_domain(cls, card: NotificationSummaryCard) -> NotificationSummaryCardResponse:
        return cls(
            notification_id=card.notification_id,
            assessment_id=card.assessment_id,
            severity=card.severity,
            status=card.status,
            metric_code=card.metric_code,
            message=card.message,
            created_at=card.created_at,
        )


class AlertDashboardResponse(BaseModel):
    total_alert_rules: int
    active_alert_rules: int
    total_notifications: int
    notifications_by_severity: dict[str, int]
    notifications_by_status: dict[str, int]
    recent_notifications: list[NotificationSummaryCardResponse]
    kpis: list[KpiWidgetResponse]
    generated_at: datetime

    @classmethod
    def from_domain(cls, dashboard: AlertDashboard) -> AlertDashboardResponse:
        return cls(
            total_alert_rules=dashboard.total_alert_rules,
            active_alert_rules=dashboard.active_alert_rules,
            total_notifications=dashboard.total_notifications,
            notifications_by_severity=dashboard.notifications_by_severity,
            notifications_by_status=dashboard.notifications_by_status,
            recent_notifications=[
                NotificationSummaryCardResponse.from_domain(n)
                for n in dashboard.recent_notifications
            ],
            kpis=[KpiWidgetResponse.from_domain(k) for k in dashboard.kpis],
            generated_at=dashboard.generated_at,
        )


class DatasetDashboardResponse(BaseModel):
    total_datasets: int
    datasets_by_type: dict[str, int]
    datasets_by_provider: dict[str, int]
    mlr_ready_count: int
    correlation_ready_count: int
    kpis: list[KpiWidgetResponse]
    generated_at: datetime

    @classmethod
    def from_domain(cls, dashboard: DatasetDashboard) -> DatasetDashboardResponse:
        return cls(
            total_datasets=dashboard.total_datasets,
            datasets_by_type=dashboard.datasets_by_type,
            datasets_by_provider=dashboard.datasets_by_provider,
            mlr_ready_count=dashboard.mlr_ready_count,
            correlation_ready_count=dashboard.correlation_ready_count,
            kpis=[KpiWidgetResponse.from_domain(k) for k in dashboard.kpis],
            generated_at=dashboard.generated_at,
        )
