"""Value objects for the Dashboard & Visualization context — pure,
frozen read-model DTOs. Sprint 12's brief is explicit: "Use projection/
read-model approach only." Unlike every other bounded context in this
codebase, Dashboard has NO aggregate root, NO domain events, and NO
repository — there is nothing here for a command to mutate and nothing to
persist. A dashboard is computed fresh, on demand, from other contexts'
already-persisted data (via ``application/ports.py``'s reader Protocols,
implemented by ``api/dashboard_ports.py``'s composition root) — the same
"conformist downstream reader" discipline Reporting (Sprint 9) and
Validation's regression extension (Sprint 10) already established, just
with no aggregate of its own sitting behind the reads. This is also why
this context has no ``infrastructure/`` package at all: there is no ORM
model, because there is nothing to store.

``KpiWidget``/``SummaryCard``/``TrendPoint`` are the three generic,
reusable shapes every dashboard below composes ("Support: KPI Widgets,
Summary Cards, Trend Analytics"); "Aggregated Metrics" and "Historical
Views" are satisfied by how these three are populated (an aggregated
count/average lands in a ``KpiWidget``/``SummaryCard``; a time-ordered
series of them is a "historical view").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class KpiWidget:
    label: str
    value: float
    unit: str = ""


@dataclass(frozen=True, slots=True)
class SummaryCard:
    label: str
    count: int
    breakdown: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TrendPoint:
    label: str
    value: float
    occurred_at: datetime


# --- Requirement #1: Dashboard Projections (per-assessment workspace) -----


@dataclass(frozen=True, slots=True)
class StageResultSummaryCard:
    stage_type: str
    status: str
    confidence_tier: str | None
    primary_indicators: dict[str, float]
    computed_at: datetime


@dataclass(frozen=True, slots=True)
class AssessmentWorkspaceProjection:
    """Requirement #1 — the per-assessment "single page" composite
    projection (Application Layer §4's ``GetAssessmentWorkspace`` in the
    fuller design): status, latest result per stage, latest prediction,
    latest validation, latest report, fanned in from five peer contexts'
    already-persisted evidence with zero writes of its own.
    """

    assessment_id: str
    name: str
    hazard_type: str
    status: str
    stage_results: tuple[StageResultSummaryCard, ...]
    latest_prediction_method: str | None
    latest_prediction_summary: str | None
    latest_validation_verdict: str | None
    latest_validation_mode: str | None
    latest_report_version: int | None
    latest_report_status: str | None
    active_notification_count: int
    generated_at: datetime


# --- Requirement #2: Executive Dashboard -----------------------------------


@dataclass(frozen=True, slots=True)
class ReportSummaryCard:
    assessment_id: str
    assessment_name: str
    report_version: int
    status: str
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class ExecutiveDashboard:
    tenant_id: str
    total_assessments: int
    assessments_by_status: dict[str, int]
    assessments_by_hazard_type: dict[str, int]
    kpis: tuple[KpiWidget, ...]
    summary_cards: tuple[SummaryCard, ...]
    recent_reports: tuple[ReportSummaryCard, ...]
    generated_at: datetime


# --- Requirements #3/#4: FIRAS/WRRAS Dashboards (shared shape) -------------


@dataclass(frozen=True, slots=True)
class HazardDashboard:
    """One shape for both the FIRAS Dashboard (``hazard_type="FLOOD"``)
    and the WRRAS Dashboard (``hazard_type="WILDFIRE"``) — the underlying
    ``StageResult`` evidence is already hazard-agnostic (Analysis Engine's
    own design, reused by Reporting's ``RiskSummarySection`` in Sprint 9
    for the identical reason): two hazard-specific classes here would just
    be two names for the same fields.
    """

    hazard_type: str
    total_assessments: int
    kpis: tuple[KpiWidget, ...]
    summary_cards: tuple[SummaryCard, ...]
    trend: tuple[TrendPoint, ...]
    generated_at: datetime


# --- Requirement #5: Prediction Dashboard ----------------------------------


@dataclass(frozen=True, slots=True)
class PredictionDashboard:
    total_prediction_runs: int
    runs_by_method: dict[str, int]
    kpis: tuple[KpiWidget, ...]
    trend: tuple[TrendPoint, ...]
    generated_at: datetime


# --- Requirement #6: Validation Dashboard ----------------------------------


@dataclass(frozen=True, slots=True)
class ValidationDashboard:
    total_validation_runs: int
    runs_by_mode: dict[str, int]
    pass_count: int
    fail_count: int
    kpis: tuple[KpiWidget, ...]
    trend: tuple[TrendPoint, ...]
    generated_at: datetime


# --- Requirement #7: Alert Dashboard ----------------------------------------


@dataclass(frozen=True, slots=True)
class NotificationSummaryCard:
    notification_id: str
    assessment_id: str
    severity: str
    status: str
    metric_code: str
    message: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AlertDashboard:
    total_alert_rules: int
    active_alert_rules: int
    total_notifications: int
    notifications_by_severity: dict[str, int]
    notifications_by_status: dict[str, int]
    recent_notifications: tuple[NotificationSummaryCard, ...]
    kpis: tuple[KpiWidget, ...]
    generated_at: datetime


# --- Requirement #8: Dataset Dashboard --------------------------------------


@dataclass(frozen=True, slots=True)
class DatasetDashboard:
    total_datasets: int
    datasets_by_type: dict[str, int]
    datasets_by_provider: dict[str, int]
    mlr_ready_count: int
    correlation_ready_count: int
    kpis: tuple[KpiWidget, ...]
    generated_at: datetime
