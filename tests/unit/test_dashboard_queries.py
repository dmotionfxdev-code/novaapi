"""Unit tests for the Dashboard query handlers — pure logic, no I/O.
Unlike every prior context's command/query handlers, these classes never
construct a repository or open a database session themselves (Sprint 12
has none of its own) — they only call the injected reader Protocols
(``application/ports.py``), so they're fully testable with plain fakes,
no real Postgres needed at all. The live composition-root readers
(``api/dashboard_ports.py``) are proven separately in
``tests/integration/test_dashboard_api.py``'s live-HTTP test.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from georisk.contexts.dashboard.application.ports import (
    AlertRuleInfo,
    AssessmentInfo,
    DatasetInfo,
    NotificationInfo,
    PredictionRunInfo,
    ReportInfo,
    StageResultInfo,
    ValidationRunInfo,
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
from georisk.contexts.dashboard.domain.errors import AssessmentNotAvailableError

pytestmark = pytest.mark.unit

_NOW = datetime.now(UTC)


class _FakeAssessmentReader:
    def __init__(
        self, info: AssessmentInfo | None = None, assessments: list[AssessmentInfo] | None = None
    ) -> None:
        self._info = info
        self._assessments = assessments or []

    async def get_assessment_info(self, *, tenant_id, assessment_id):  # noqa: ANN001
        return self._info

    async def list_assessments(self, *, tenant_id, hazard_type, limit):  # noqa: ANN001
        if hazard_type is None:
            return self._assessments
        return [a for a in self._assessments if a.hazard_type == hazard_type]


class _FakeStageResultReader:
    def __init__(self, by_assessment: dict[tuple[str, str], StageResultInfo]) -> None:
        self._by_assessment = by_assessment

    async def get_latest_stage_result(self, *, tenant_id, assessment_id, stage_type):  # noqa: ANN001
        return self._by_assessment.get((assessment_id, stage_type))


class _FakePredictionReader:
    def __init__(self, by_assessment: dict[str, list[PredictionRunInfo]]) -> None:
        self._by_assessment = by_assessment

    async def list_prediction_runs(self, *, tenant_id, assessment_id):  # noqa: ANN001
        return self._by_assessment.get(assessment_id, [])


class _FakeValidationReader:
    def __init__(self, by_assessment: dict[str, list[ValidationRunInfo]]) -> None:
        self._by_assessment = by_assessment

    async def list_validation_runs(self, *, tenant_id, assessment_id):  # noqa: ANN001
        return self._by_assessment.get(assessment_id, [])


class _FakeNotificationReader:
    def __init__(
        self,
        notifications: list[NotificationInfo] | None = None,
        alert_rules: list[AlertRuleInfo] | None = None,
        assessment_counts: dict[str, int] | None = None,
    ) -> None:
        self._notifications = notifications or []
        self._alert_rules = alert_rules or []
        self._assessment_counts = assessment_counts or {}

    async def list_notifications(self, *, tenant_id, limit):  # noqa: ANN001
        return self._notifications[:limit]

    async def list_alert_rules(self, *, tenant_id):  # noqa: ANN001
        return self._alert_rules

    async def count_notifications_for_assessment(self, *, tenant_id, assessment_id):  # noqa: ANN001
        return self._assessment_counts.get(assessment_id, 0)


class _FakeDatasetReader:
    def __init__(self, datasets: list[DatasetInfo]) -> None:
        self._datasets = datasets

    async def list_datasets(self, *, tenant_id):  # noqa: ANN001
        return self._datasets


class _FakeReportReader:
    def __init__(
        self, latest: ReportInfo | None = None, tenant_reports: list[ReportInfo] | None = None
    ) -> None:
        self._latest = latest
        self._tenant_reports = tenant_reports or []

    async def get_latest_report(self, *, tenant_id, assessment_id):  # noqa: ANN001
        return self._latest

    async def list_latest_reports(self, *, tenant_id, limit):  # noqa: ANN001
        return self._tenant_reports[:limit]


async def test_assessment_workspace_raises_when_assessment_not_found() -> None:
    query = GetAssessmentWorkspaceQuery(
        _FakeAssessmentReader(info=None),
        _FakeStageResultReader({}),
        _FakePredictionReader({}),
        _FakeValidationReader({}),
        _FakeReportReader(),
        _FakeNotificationReader(),
    )
    with pytest.raises(AssessmentNotAvailableError):
        await query.handle(tenant_id="t1", assessment_id="a1")


async def test_assessment_workspace_composes_every_section() -> None:
    assessment_info = AssessmentInfo("a1", "Test Assessment", "FLOOD", "VALIDATED", _NOW)
    risk_stage = StageResultInfo("RISK", "COMPLETE", "LOW", {"flood_risk_index": 0.11}, _NOW)
    prediction = PredictionRunInfo("p1", "MULTIPLE_LINEAR_REGRESSION", 0.87, 0.08, _NOW)
    validation = ValidationRunInfo("v1", "REGRESSION", "PASS", _NOW)
    report = ReportInfo("a1", "Test Assessment", 1, "FINALIZED", _NOW)

    query = GetAssessmentWorkspaceQuery(
        _FakeAssessmentReader(info=assessment_info),
        _FakeStageResultReader({("a1", "RISK"): risk_stage}),
        _FakePredictionReader({"a1": [prediction]}),
        _FakeValidationReader({"a1": [validation]}),
        _FakeReportReader(latest=report),
        _FakeNotificationReader(assessment_counts={"a1": 2}),
    )
    workspace = await query.handle(tenant_id="t1", assessment_id="a1")

    assert workspace.hazard_type == "FLOOD"
    assert len(workspace.stage_results) == 1
    assert workspace.stage_results[0].stage_type == "RISK"
    assert workspace.latest_prediction_method == "MULTIPLE_LINEAR_REGRESSION"
    assert workspace.latest_prediction_summary == "R²=0.87"
    assert workspace.latest_validation_verdict == "PASS"
    assert workspace.latest_report_version == 1
    assert workspace.active_notification_count == 2


async def test_executive_dashboard_aggregates_across_assessments() -> None:
    assessments = [
        AssessmentInfo("a1", "One", "FLOOD", "VALIDATED", _NOW),
        AssessmentInfo("a2", "Two", "WILDFIRE", "DRAFT", _NOW),
        AssessmentInfo("a3", "Three", "FLOOD", "VALIDATED", _NOW),
    ]
    alert_rules = [AlertRuleInfo("r1", True), AlertRuleInfo("r2", False)]
    notifications = [
        NotificationInfo("n1", "a1", "HIGH", "SENT", "flood_risk_index", "msg", _NOW),
        NotificationInfo("n2", "a1", "MEDIUM", "FAILED", "rmse", "msg", _NOW),
    ]
    reports = [ReportInfo("a1", "One", 1, "FINALIZED", _NOW)]

    query = GetExecutiveDashboardQuery(
        _FakeAssessmentReader(assessments=assessments),
        _FakeNotificationReader(notifications=notifications, alert_rules=alert_rules),
        _FakeReportReader(tenant_reports=reports),
    )
    dashboard = await query.handle(tenant_id="t1")

    assert dashboard.total_assessments == 3
    assert dashboard.assessments_by_status == {"VALIDATED": 2, "DRAFT": 1}
    assert dashboard.assessments_by_hazard_type == {"FLOOD": 2, "WILDFIRE": 1}
    kpi_labels = {k.label: k.value for k in dashboard.kpis}
    assert kpi_labels["Active Alert Rules"] == 1.0
    assert kpi_labels["Notifications Sent"] == 1.0
    assert kpi_labels["Notifications Failed"] == 1.0
    assert len(dashboard.recent_reports) == 1


async def test_hazard_dashboard_filters_by_hazard_type_and_builds_trend() -> None:
    assessments = [
        AssessmentInfo("a1", "Flood One", "FLOOD", "VALIDATED", _NOW),
        AssessmentInfo("a2", "Wildfire One", "WILDFIRE", "VALIDATED", _NOW),
    ]
    stage_results = {
        ("a1", "RISK"): StageResultInfo("RISK", "COMPLETE", "LOW", {"flood_risk_index": 0.2}, _NOW),
        ("a2", "RISK"): StageResultInfo(
            "RISK", "COMPLETE", "LOW", {"wildfire_risk_index": 0.9}, _NOW
        ),
    }
    query = GetHazardDashboardQuery(
        _FakeAssessmentReader(assessments=assessments), _FakeStageResultReader(stage_results)
    )
    dashboard = await query.handle(tenant_id="t1", hazard_type="FLOOD")

    assert dashboard.hazard_type == "FLOOD"
    assert dashboard.total_assessments == 1
    assert len(dashboard.trend) == 1
    assert dashboard.trend[0].value == pytest.approx(0.2)
    kpi_labels = {k.label: k.value for k in dashboard.kpis}
    assert kpi_labels["Average Risk Index"] == pytest.approx(0.2)


async def test_prediction_dashboard_computes_averages() -> None:
    assessments = [AssessmentInfo("a1", "One", "FLOOD", "VALIDATED", _NOW)]
    runs = {
        "a1": [
            PredictionRunInfo("p1", "MULTIPLE_LINEAR_REGRESSION", 0.8, 0.1, _NOW),
            PredictionRunInfo("p2", "PEARSON_CORRELATION", None, None, _NOW),
        ]
    }
    query = GetPredictionDashboardQuery(
        _FakeAssessmentReader(assessments=assessments), _FakePredictionReader(runs)
    )
    dashboard = await query.handle(tenant_id="t1")

    assert dashboard.total_prediction_runs == 2
    assert dashboard.runs_by_method == {
        "MULTIPLE_LINEAR_REGRESSION": 1,
        "PEARSON_CORRELATION": 1,
    }
    kpi_labels = {k.label: k.value for k in dashboard.kpis}
    assert kpi_labels["Average R-squared"] == pytest.approx(0.8)
    assert len(dashboard.trend) == 1


async def test_validation_dashboard_computes_pass_rate() -> None:
    assessments = [AssessmentInfo("a1", "One", "FLOOD", "VALIDATED", _NOW)]
    runs = {
        "a1": [
            ValidationRunInfo("v1", "CLASSIFICATION", "PASS", _NOW),
            ValidationRunInfo("v2", "REGRESSION", "FAIL", _NOW),
            ValidationRunInfo("v3", "REGRESSION", "PASS", _NOW),
        ]
    }
    query = GetValidationDashboardQuery(
        _FakeAssessmentReader(assessments=assessments), _FakeValidationReader(runs)
    )
    dashboard = await query.handle(tenant_id="t1")

    assert dashboard.total_validation_runs == 3
    assert dashboard.pass_count == 2
    assert dashboard.fail_count == 1
    kpi_labels = {k.label: k.value for k in dashboard.kpis}
    assert kpi_labels["Pass Rate"] == pytest.approx(2 / 3)


async def test_alert_dashboard_groups_by_severity_and_status() -> None:
    alert_rules = [AlertRuleInfo("r1", True), AlertRuleInfo("r2", True), AlertRuleInfo("r3", False)]
    notifications = [
        NotificationInfo("n1", "a1", "HIGH", "SENT", "flood_risk_index", "msg", _NOW),
        NotificationInfo("n2", "a1", "HIGH", "FAILED", "rmse", "msg", _NOW),
        NotificationInfo("n3", "a1", "CRITICAL", "SENT", "r_squared", "msg", _NOW),
    ]
    query = GetAlertDashboardQuery(
        _FakeNotificationReader(notifications=notifications, alert_rules=alert_rules)
    )
    dashboard = await query.handle(tenant_id="t1")

    assert dashboard.total_alert_rules == 3
    assert dashboard.active_alert_rules == 2
    assert dashboard.total_notifications == 3
    assert dashboard.notifications_by_severity == {"HIGH": 2, "CRITICAL": 1}
    assert dashboard.notifications_by_status == {"SENT": 2, "FAILED": 1}
    assert len(dashboard.recent_notifications) == 3


async def test_dataset_dashboard_groups_by_type_and_readiness() -> None:
    datasets = [
        DatasetInfo("d1", "RASTER", "CHIRPS", True, False),
        DatasetInfo("d2", "VECTOR", "USER_UPLOAD", False, True),
        DatasetInfo("d3", "RASTER", "MODIS", True, True),
    ]
    query = GetDatasetDashboardQuery(_FakeDatasetReader(datasets))
    dashboard = await query.handle(tenant_id="t1")

    assert dashboard.total_datasets == 3
    assert dashboard.datasets_by_type == {"RASTER": 2, "VECTOR": 1}
    assert dashboard.mlr_ready_count == 2
    assert dashboard.correlation_ready_count == 2
