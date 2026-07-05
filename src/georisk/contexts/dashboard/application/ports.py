"""Ports the Dashboard context needs from every peer it visualizes —
Assessment, Analysis Engine, Prediction, Validation, Notification, Data
Acquisition, and Reporting. Dashboard's own bounded context may not
import any of these peers directly (import-linter's independence
contract), so these Protocols are the seam: a composition-root module
(``api/dashboard_ports.py``, outside every context involved — the same
role ``api/reporting_ports.py``/``api/notification_ports.py`` already
play) implements each reader by calling that context's own repository
directly.

Every reader here is read-only by construction — none of these Protocols
expose a method that could mutate anything, structurally enforcing
"Use projection/read-model approach only" (Sprint 12's own constraint) at
the type level, not just by convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AssessmentInfo:
    assessment_id: str
    name: str
    hazard_type: str
    status: str
    created_at: datetime


class AssessmentReader(Protocol):
    async def get_assessment_info(
        self, *, tenant_id: str, assessment_id: str
    ) -> AssessmentInfo | None: ...

    async def list_assessments(
        self, *, tenant_id: str, hazard_type: str | None, limit: int
    ) -> list[AssessmentInfo]:
        """The most recent ``limit`` assessments for this tenant,
        optionally scoped to one hazard type — what the Executive/FIRAS/
        WRRAS dashboards fan out from."""
        ...


@dataclass(frozen=True, slots=True)
class StageResultInfo:
    stage_type: str
    status: str
    confidence_tier: str | None
    indicators: dict[str, float]
    computed_at: datetime


class StageResultReader(Protocol):
    async def get_latest_stage_result(
        self, *, tenant_id: str, assessment_id: str, stage_type: str
    ) -> StageResultInfo | None: ...


@dataclass(frozen=True, slots=True)
class PredictionRunInfo:
    prediction_run_id: str
    method: str
    r_squared: float | None
    rmse: float | None
    computed_at: datetime


class PredictionReader(Protocol):
    async def list_prediction_runs(
        self, *, tenant_id: str, assessment_id: str
    ) -> list[PredictionRunInfo]: ...


@dataclass(frozen=True, slots=True)
class ValidationRunInfo:
    validation_run_id: str
    mode: str
    verdict: str | None
    computed_at: datetime


class ValidationReader(Protocol):
    async def list_validation_runs(
        self, *, tenant_id: str, assessment_id: str
    ) -> list[ValidationRunInfo]: ...


@dataclass(frozen=True, slots=True)
class NotificationInfo:
    notification_id: str
    assessment_id: str
    severity: str
    status: str
    metric_code: str
    message: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AlertRuleInfo:
    alert_rule_id: str
    is_active: bool


class NotificationReader(Protocol):
    async def list_notifications(self, *, tenant_id: str, limit: int) -> list[NotificationInfo]:
        """Tenant-wide notification history, newest first — Notification
        already built a genuine tenant-wide history query in Sprint 11
        (``list_by_tenant``), so this reader needs no per-assessment
        fan-out, unlike ``StageResultReader``/``PredictionReader``/
        ``ValidationReader`` above."""
        ...

    async def list_alert_rules(self, *, tenant_id: str) -> list[AlertRuleInfo]: ...

    async def count_notifications_for_assessment(
        self, *, tenant_id: str, assessment_id: str
    ) -> int:
        """Used only by the per-assessment workspace projection —
        Notification's own ``list_by_assessment`` (Sprint 11), counted."""
        ...


@dataclass(frozen=True, slots=True)
class DatasetInfo:
    dataset_id: str
    dataset_type: str
    provider: str
    is_mlr_ready: bool
    is_correlation_ready: bool


class DatasetReader(Protocol):
    async def list_datasets(self, *, tenant_id: str) -> list[DatasetInfo]:
        """Every current (non-superseded) dataset — Data Acquisition
        already built a tenant-wide catalog query in Sprint 7
        (``list_catalog``), so this reader needs no fan-out either."""
        ...


@dataclass(frozen=True, slots=True)
class ReportInfo:
    assessment_id: str
    assessment_name: str | None
    version: int
    status: str
    generated_at: datetime


class ReportReader(Protocol):
    async def get_latest_report(
        self, *, tenant_id: str, assessment_id: str
    ) -> ReportInfo | None: ...

    async def list_latest_reports(self, *, tenant_id: str, limit: int) -> list[ReportInfo]:
        """One row per assessment (the latest report version) — Reporting
        already built exactly this tenant-wide projection in Sprint 9
        (``list_latest_by_tenant``), so this reader needs no fan-out
        either."""
        ...
