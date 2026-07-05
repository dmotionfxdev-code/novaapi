"""Query handlers — read-only, never mutate, no command pipeline exists in
this context at all (Sprint 12's "projection/read-model approach only").
Every query below gathers via the injected reader ports
(``application/ports.py``), then hands the raw data to
``domain/aggregation.py``'s pure functions to build the final
``KpiWidget``/``SummaryCard``/``TrendPoint`` tuples — no aggregation logic
is duplicated per-dashboard.

Cross-assessment dashboards (Executive/FIRAS/WRRAS/Prediction/Validation)
fan out from ``AssessmentReader.list_assessments`` since Analysis Engine's
``StageResult`` and Prediction's ``PredictionRun`` only have per-assessment
list methods (no tenant-wide one exists, and none is added here — "Use
projection/read-model approach only" is read as "Dashboard reads what
already exists," never as license to extend another context's repository).
``_MAX_ASSESSMENTS_PER_DASHBOARD`` bounds the resulting fan-out width, the
same "deliberate, documented cap" precedent
``prediction.domain.correlation.MAX_KENDALL_OBSERVATIONS`` already set.
"""

from __future__ import annotations

from datetime import UTC, datetime

from georisk.contexts.dashboard.application.ports import (
    AssessmentReader,
    DatasetReader,
    NotificationReader,
    PredictionReader,
    ReportReader,
    StageResultReader,
    ValidationReader,
)
from georisk.contexts.dashboard.domain.aggregation import average, build_trend, count_by, rate
from georisk.contexts.dashboard.domain.errors import AssessmentNotAvailableError
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
    ValidationDashboard,
)

_CORE_STAGE_TYPES = ("HAZARD", "EXPOSURE", "VULNERABILITY", "RISK", "RESILIENCE")
_MAX_ASSESSMENTS_PER_DASHBOARD = 200
_MAX_RECENT_ITEMS = 10


class GetAssessmentWorkspaceQuery:
    """Requirement #1 — Dashboard Projections (per-assessment)."""

    def __init__(
        self,
        assessment_reader: AssessmentReader,
        stage_result_reader: StageResultReader,
        prediction_reader: PredictionReader,
        validation_reader: ValidationReader,
        report_reader: ReportReader,
        notification_reader: NotificationReader,
    ) -> None:
        self._assessment_reader = assessment_reader
        self._stage_result_reader = stage_result_reader
        self._prediction_reader = prediction_reader
        self._validation_reader = validation_reader
        self._report_reader = report_reader
        self._notification_reader = notification_reader

    async def handle(self, *, tenant_id: str, assessment_id: str) -> AssessmentWorkspaceProjection:
        assessment = await self._assessment_reader.get_assessment_info(
            tenant_id=tenant_id, assessment_id=assessment_id
        )
        if assessment is None:
            raise AssessmentNotAvailableError(f"Assessment {assessment_id} not found")

        stage_cards = []
        for stage_type in _CORE_STAGE_TYPES:
            stage_result = await self._stage_result_reader.get_latest_stage_result(
                tenant_id=tenant_id, assessment_id=assessment_id, stage_type=stage_type
            )
            if stage_result is not None:
                stage_cards.append(
                    StageResultSummaryCard(
                        stage_type=stage_result.stage_type,
                        status=stage_result.status,
                        confidence_tier=stage_result.confidence_tier,
                        primary_indicators=stage_result.indicators,
                        computed_at=stage_result.computed_at,
                    )
                )

        # Both readers return newest-first (documented on the composition
        # root) so index [0] is always "latest" here.
        prediction_runs = await self._prediction_reader.list_prediction_runs(
            tenant_id=tenant_id, assessment_id=assessment_id
        )
        latest_prediction = prediction_runs[0] if prediction_runs else None
        prediction_summary = None
        if latest_prediction is not None:
            if latest_prediction.r_squared is not None:
                prediction_summary = f"R²={latest_prediction.r_squared}"
            elif latest_prediction.rmse is not None:
                prediction_summary = f"RMSE={latest_prediction.rmse}"

        validation_runs = await self._validation_reader.list_validation_runs(
            tenant_id=tenant_id, assessment_id=assessment_id
        )
        latest_validation = validation_runs[0] if validation_runs else None

        report = await self._report_reader.get_latest_report(
            tenant_id=tenant_id, assessment_id=assessment_id
        )
        notification_count = await self._notification_reader.count_notifications_for_assessment(
            tenant_id=tenant_id, assessment_id=assessment_id
        )

        return AssessmentWorkspaceProjection(
            assessment_id=assessment.assessment_id,
            name=assessment.name,
            hazard_type=assessment.hazard_type,
            status=assessment.status,
            stage_results=tuple(stage_cards),
            latest_prediction_method=(
                latest_prediction.method if latest_prediction is not None else None
            ),
            latest_prediction_summary=prediction_summary,
            latest_validation_verdict=(
                latest_validation.verdict if latest_validation is not None else None
            ),
            latest_validation_mode=(
                latest_validation.mode if latest_validation is not None else None
            ),
            latest_report_version=report.version if report is not None else None,
            latest_report_status=report.status if report is not None else None,
            active_notification_count=notification_count,
            generated_at=datetime.now(UTC),
        )


class GetExecutiveDashboardQuery:
    """Requirement #2."""

    def __init__(
        self,
        assessment_reader: AssessmentReader,
        notification_reader: NotificationReader,
        report_reader: ReportReader,
    ) -> None:
        self._assessment_reader = assessment_reader
        self._notification_reader = notification_reader
        self._report_reader = report_reader

    async def handle(self, *, tenant_id: str) -> ExecutiveDashboard:
        assessments = await self._assessment_reader.list_assessments(
            tenant_id=tenant_id, hazard_type=None, limit=_MAX_ASSESSMENTS_PER_DASHBOARD
        )
        alert_rules = await self._notification_reader.list_alert_rules(tenant_id=tenant_id)
        notifications = await self._notification_reader.list_notifications(
            tenant_id=tenant_id, limit=_MAX_ASSESSMENTS_PER_DASHBOARD
        )
        reports = await self._report_reader.list_latest_reports(
            tenant_id=tenant_id, limit=_MAX_ASSESSMENTS_PER_DASHBOARD
        )

        by_status = count_by(assessments, lambda a: a.status)
        by_hazard = count_by(assessments, lambda a: a.hazard_type)
        active_rules = sum(1 for r in alert_rules if r.is_active)
        sent = sum(1 for n in notifications if n.status == "SENT")
        failed = sum(1 for n in notifications if n.status == "FAILED")

        kpis = (
            KpiWidget("Total Assessments", float(len(assessments))),
            KpiWidget("Active Alert Rules", float(active_rules)),
            KpiWidget("Notifications Sent", float(sent)),
            KpiWidget("Notifications Failed", float(failed)),
        )
        summary_cards = (
            SummaryCard("Assessments by Status", len(assessments), by_status),
            SummaryCard("Assessments by Hazard Type", len(assessments), by_hazard),
        )
        recent_reports = tuple(
            ReportSummaryCard(
                assessment_id=r.assessment_id,
                assessment_name=r.assessment_name or "",
                report_version=r.version,
                status=r.status,
                generated_at=r.generated_at,
            )
            for r in sorted(reports, key=lambda r: r.generated_at, reverse=True)[
                :_MAX_RECENT_ITEMS
            ]
        )
        return ExecutiveDashboard(
            tenant_id=tenant_id,
            total_assessments=len(assessments),
            assessments_by_status=by_status,
            assessments_by_hazard_type=by_hazard,
            kpis=kpis,
            summary_cards=summary_cards,
            recent_reports=recent_reports,
            generated_at=datetime.now(UTC),
        )


class GetHazardDashboardQuery:
    """Requirements #3/#4 — FIRAS (``hazard_type="FLOOD"``) and WRRAS
    (``hazard_type="WILDFIRE"``) share this one query, parametrized by
    hazard type — see ``HazardDashboard``'s docstring for why."""

    def __init__(
        self, assessment_reader: AssessmentReader, stage_result_reader: StageResultReader
    ) -> None:
        self._assessment_reader = assessment_reader
        self._stage_result_reader = stage_result_reader

    async def handle(self, *, tenant_id: str, hazard_type: str) -> HazardDashboard:
        assessments = await self._assessment_reader.list_assessments(
            tenant_id=tenant_id, hazard_type=hazard_type, limit=_MAX_ASSESSMENTS_PER_DASHBOARD
        )

        risk_results = []
        for assessment in assessments:
            stage_result = await self._stage_result_reader.get_latest_stage_result(
                tenant_id=tenant_id, assessment_id=assessment.assessment_id, stage_type="RISK"
            )
            if stage_result is not None:
                risk_results.append((assessment, stage_result))

        confidence_counts = count_by(
            [sr for _a, sr in risk_results], lambda sr: sr.confidence_tier or "UNKNOWN"
        )
        # The RISK stage always produces exactly one indicator (FIRAS's
        # flood_risk_index / WRRAS's wildfire_risk_index) — Analysis
        # Engine's own design (Sprint 5/6) — so the single value present
        # is unambiguously "the" risk index for that assessment.
        risk_values = [
            v for _a, sr in risk_results for v in sr.indicators.values()
        ]

        kpis = [KpiWidget("Assessments", float(len(assessments)))]
        avg_risk = average(risk_values)
        if avg_risk is not None:
            kpis.append(KpiWidget("Average Risk Index", avg_risk))
            kpis.append(KpiWidget("Max Risk Index", max(risk_values)))

        summary_cards = (
            SummaryCard("Risk Results by Confidence Tier", len(risk_results), confidence_counts),
        )
        trend = build_trend(
            risk_results,
            label=lambda pair: pair[0].name,
            value=lambda pair: next(iter(pair[1].indicators.values()), 0.0),
            occurred_at=lambda pair: pair[1].computed_at,
        )
        return HazardDashboard(
            hazard_type=hazard_type,
            total_assessments=len(assessments),
            kpis=tuple(kpis),
            summary_cards=summary_cards,
            trend=trend,
            generated_at=datetime.now(UTC),
        )


class GetPredictionDashboardQuery:
    """Requirement #5."""

    def __init__(
        self, assessment_reader: AssessmentReader, prediction_reader: PredictionReader
    ) -> None:
        self._assessment_reader = assessment_reader
        self._prediction_reader = prediction_reader

    async def handle(self, *, tenant_id: str) -> PredictionDashboard:
        assessments = await self._assessment_reader.list_assessments(
            tenant_id=tenant_id, hazard_type=None, limit=_MAX_ASSESSMENTS_PER_DASHBOARD
        )
        all_runs = []
        for assessment in assessments:
            all_runs.extend(
                await self._prediction_reader.list_prediction_runs(
                    tenant_id=tenant_id, assessment_id=assessment.assessment_id
                )
            )

        by_method = count_by(all_runs, lambda r: r.method)
        avg_r2 = average([r.r_squared for r in all_runs if r.r_squared is not None])
        avg_rmse = average([r.rmse for r in all_runs if r.rmse is not None])

        kpis = [KpiWidget("Total Prediction Runs", float(len(all_runs)))]
        if avg_r2 is not None:
            kpis.append(KpiWidget("Average R-squared", avg_r2))
        if avg_rmse is not None:
            kpis.append(KpiWidget("Average RMSE", avg_rmse))

        trend = build_trend(
            [r for r in all_runs if r.r_squared is not None],
            label=lambda r: r.method,
            value=lambda r: r.r_squared,  # type: ignore[arg-type,return-value]
            occurred_at=lambda r: r.computed_at,
        )
        return PredictionDashboard(
            total_prediction_runs=len(all_runs),
            runs_by_method=by_method,
            kpis=tuple(kpis),
            trend=trend,
            generated_at=datetime.now(UTC),
        )


class GetValidationDashboardQuery:
    """Requirement #6."""

    def __init__(
        self, assessment_reader: AssessmentReader, validation_reader: ValidationReader
    ) -> None:
        self._assessment_reader = assessment_reader
        self._validation_reader = validation_reader

    async def handle(self, *, tenant_id: str) -> ValidationDashboard:
        assessments = await self._assessment_reader.list_assessments(
            tenant_id=tenant_id, hazard_type=None, limit=_MAX_ASSESSMENTS_PER_DASHBOARD
        )
        all_runs = []
        for assessment in assessments:
            all_runs.extend(
                await self._validation_reader.list_validation_runs(
                    tenant_id=tenant_id, assessment_id=assessment.assessment_id
                )
            )

        by_mode = count_by(all_runs, lambda r: r.mode)
        pass_count = sum(1 for r in all_runs if r.verdict == "PASS")
        fail_count = sum(1 for r in all_runs if r.verdict == "FAIL")

        kpis = (
            KpiWidget("Total Validation Runs", float(len(all_runs))),
            KpiWidget("Pass Rate", rate(pass_count, pass_count + fail_count), unit="ratio"),
        )
        trend = build_trend(
            [r for r in all_runs if r.verdict is not None],
            label=lambda r: r.mode,
            value=lambda r: 1.0 if r.verdict == "PASS" else 0.0,
            occurred_at=lambda r: r.computed_at,
        )
        return ValidationDashboard(
            total_validation_runs=len(all_runs),
            runs_by_mode=by_mode,
            pass_count=pass_count,
            fail_count=fail_count,
            kpis=kpis,
            trend=trend,
            generated_at=datetime.now(UTC),
        )


class GetAlertDashboardQuery:
    """Requirement #7."""

    def __init__(self, notification_reader: NotificationReader) -> None:
        self._notification_reader = notification_reader

    async def handle(self, *, tenant_id: str) -> AlertDashboard:
        alert_rules = await self._notification_reader.list_alert_rules(tenant_id=tenant_id)
        notifications = await self._notification_reader.list_notifications(
            tenant_id=tenant_id, limit=_MAX_ASSESSMENTS_PER_DASHBOARD
        )

        active_rules = sum(1 for r in alert_rules if r.is_active)
        by_severity = count_by(notifications, lambda n: n.severity)
        by_status = count_by(notifications, lambda n: n.status)
        recent = tuple(
            NotificationSummaryCard(
                notification_id=n.notification_id,
                assessment_id=n.assessment_id,
                severity=n.severity,
                status=n.status,
                metric_code=n.metric_code,
                message=n.message,
                created_at=n.created_at,
            )
            for n in notifications[:_MAX_RECENT_ITEMS]
        )
        kpis = (
            KpiWidget("Total Alert Rules", float(len(alert_rules))),
            KpiWidget("Active Alert Rules", float(active_rules)),
            KpiWidget("Total Notifications", float(len(notifications))),
        )
        return AlertDashboard(
            total_alert_rules=len(alert_rules),
            active_alert_rules=active_rules,
            total_notifications=len(notifications),
            notifications_by_severity=by_severity,
            notifications_by_status=by_status,
            recent_notifications=recent,
            kpis=kpis,
            generated_at=datetime.now(UTC),
        )


class GetDatasetDashboardQuery:
    """Requirement #8."""

    def __init__(self, dataset_reader: DatasetReader) -> None:
        self._dataset_reader = dataset_reader

    async def handle(self, *, tenant_id: str) -> DatasetDashboard:
        datasets = await self._dataset_reader.list_datasets(tenant_id=tenant_id)
        by_type = count_by(datasets, lambda d: d.dataset_type)
        by_provider = count_by(datasets, lambda d: d.provider)
        mlr_ready = sum(1 for d in datasets if d.is_mlr_ready)
        correlation_ready = sum(1 for d in datasets if d.is_correlation_ready)

        kpis = (
            KpiWidget("Total Datasets", float(len(datasets))),
            KpiWidget("MLR-Ready Datasets", float(mlr_ready)),
            KpiWidget("Correlation-Ready Datasets", float(correlation_ready)),
        )
        return DatasetDashboard(
            total_datasets=len(datasets),
            datasets_by_type=by_type,
            datasets_by_provider=by_provider,
            mlr_ready_count=mlr_ready,
            correlation_ready_count=correlation_ready,
            kpis=kpis,
            generated_at=datetime.now(UTC),
        )
