"""Composition-root glue wiring Assessment, Analysis Engine, Prediction,
Validation, Notification, Data Acquisition, and Reporting into
Dashboard's own read-only Protocol ports
(``contexts/dashboard/application/ports.py``). Lives here, under
``api/``, deliberately outside every context involved — the import-
linter's peer-independence contract forbids any bounded context from
importing another, so the only place code needing all of these contexts'
repositories can legally live is a neutral composition layer, the
identical role ``api/reporting_ports.py``/``api/notification_ports.py``/
``api/validation_ports.py`` already play.

Every reader here only ever calls another context's existing repository
methods — none of those contexts' infrastructure was extended for this
sprint (StageResult/PredictionRun/ValidationRun only expose per-assessment
list methods, so the cross-assessment dashboards fan out from
``CompositionRootAssessmentReader.list_assessments`` rather than a new
tenant-wide method being added anywhere else — see
``application/queries.py``'s module docstring for the full reasoning).

Both ``list_prediction_runs``/``list_validation_runs`` are normalized to
newest-first here, uniformly, regardless of each upstream repository's own
raw ordering convention — Dashboard's own contract, documented once here
rather than left for every query handler to reason about independently.
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.value_objects import StageType as AnalysisStageType
from georisk.contexts.analysis.infrastructure.repositories import SqlAlchemyStageResultRepository
from georisk.contexts.assessment.domain.value_objects import AssessmentId, HazardType
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
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
from georisk.contexts.data_acquisition.domain.value_objects import DatasetReadinessTag
from georisk.contexts.data_acquisition.infrastructure.repositories import (
    SqlAlchemyDatasetRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.notification.infrastructure.repositories import (
    SqlAlchemyAlertRuleRepository,
    SqlAlchemyNotificationRepository,
)
from georisk.contexts.prediction.domain.value_objects import PredictionRunStatus
from georisk.contexts.prediction.infrastructure.repositories import (
    SqlAlchemyPredictionRunRepository,
)
from georisk.contexts.reporting.infrastructure.repositories import SqlAlchemyReportRepository
from georisk.contexts.validation.domain.value_objects import ValidationRunStatus
from georisk.contexts.validation.infrastructure.repositories import (
    SqlAlchemyValidationRunRepository,
)
from georisk.db.session import Database


class CompositionRootAssessmentReader:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_assessment_info(
        self, *, tenant_id: str, assessment_id: str
    ) -> AssessmentInfo | None:
        async with self._db.session() as session:
            repo = SqlAlchemyAssessmentRepository(session)
            assessment = await repo.get_by_id(AssessmentId.from_string(assessment_id))
            if assessment is None or str(assessment.tenant_id) != tenant_id:
                return None
            return AssessmentInfo(
                assessment_id=str(assessment.id),
                name=assessment.name,
                hazard_type=assessment.hazard_type.value,
                status=assessment.status.value,
                created_at=assessment.created_at,
            )

    async def list_assessments(
        self, *, tenant_id: str, hazard_type: str | None, limit: int
    ) -> list[AssessmentInfo]:
        async with self._db.session() as session:
            repo = SqlAlchemyAssessmentRepository(session)
            assessments, _cursor, _has_more = await repo.list_by_tenant(
                TenantId.from_string(tenant_id),
                limit=limit,
                cursor=None,
                hazard_type=HazardType(hazard_type) if hazard_type else None,
            )
            return [
                AssessmentInfo(
                    assessment_id=str(a.id),
                    name=a.name,
                    hazard_type=a.hazard_type.value,
                    status=a.status.value,
                    created_at=a.created_at,
                )
                for a in assessments
            ]


class CompositionRootStageResultReader:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_latest_stage_result(
        self, *, tenant_id: str, assessment_id: str, stage_type: str
    ) -> StageResultInfo | None:
        try:
            resolved_stage_type = AnalysisStageType(stage_type)
        except ValueError:
            return None

        async with self._db.session() as session:
            repo = SqlAlchemyStageResultRepository(session)
            stage_result = await repo.get_latest(
                TenantId.from_string(tenant_id), assessment_id, resolved_stage_type
            )
            if stage_result is None:
                return None
            return StageResultInfo(
                stage_type=stage_result.stage_type.value,
                status=stage_result.status.value,
                confidence_tier=(
                    stage_result.confidence_tier.value
                    if stage_result.confidence_tier is not None
                    else None
                ),
                indicators=(
                    stage_result.indicators.as_dict()
                    if stage_result.indicators is not None
                    else {}
                ),
                computed_at=stage_result.created_at,
            )


class CompositionRootPredictionReader:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_prediction_runs(
        self, *, tenant_id: str, assessment_id: str
    ) -> list[PredictionRunInfo]:
        async with self._db.session() as session:
            repo = SqlAlchemyPredictionRunRepository(session)
            runs = await repo.list_by_assessment(TenantId.from_string(tenant_id), assessment_id)
            # Already newest-first (repository docstring) — no re-sort needed.
            return [
                PredictionRunInfo(
                    prediction_run_id=str(run.id),
                    method=run.method.value,
                    r_squared=(
                        run.regression_result.r_squared
                        if run.regression_result is not None
                        else None
                    ),
                    rmse=(
                        run.regression_result.rmse if run.regression_result is not None else None
                    ),
                    computed_at=run.created_at,
                )
                for run in runs
                if run.status is PredictionRunStatus.COMPLETED
            ]


class CompositionRootValidationReader:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_validation_runs(
        self, *, tenant_id: str, assessment_id: str
    ) -> list[ValidationRunInfo]:
        async with self._db.session() as session:
            repo = SqlAlchemyValidationRunRepository(session)
            runs, _cursor, _has_more = await repo.list_by_assessment(
                TenantId.from_string(tenant_id), assessment_id, limit=1000, cursor=None
            )
            # Repository docstring: oldest-first — reverse to Dashboard's
            # own newest-first contract.
            infos = [
                ValidationRunInfo(
                    validation_run_id=str(run.id),
                    mode=run.mode.value,
                    verdict=run.verdict.value if run.verdict is not None else None,
                    computed_at=run.created_at,
                )
                for run in runs
                if run.status is ValidationRunStatus.COMPLETED
            ]
            return list(reversed(infos))


class CompositionRootNotificationReader:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_notifications(self, *, tenant_id: str, limit: int) -> list[NotificationInfo]:
        async with self._db.session() as session:
            repo = SqlAlchemyNotificationRepository(session)
            notifications, _cursor, _has_more = await repo.list_by_tenant(
                TenantId.from_string(tenant_id), limit=limit, cursor=None
            )
            # Repository is oldest-first (cursor-pagination convention) —
            # reverse to Dashboard's own newest-first contract.
            infos = [
                NotificationInfo(
                    notification_id=str(n.id),
                    assessment_id=n.assessment_id,
                    severity=n.severity.value,
                    status=n.status.value,
                    metric_code=n.metric_code,
                    message=n.message,
                    created_at=n.created_at,
                )
                for n in notifications
            ]
            return list(reversed(infos))

    async def list_alert_rules(self, *, tenant_id: str) -> list[AlertRuleInfo]:
        async with self._db.session() as session:
            repo = SqlAlchemyAlertRuleRepository(session)
            rules = await repo.list_by_tenant(TenantId.from_string(tenant_id))
            return [
                AlertRuleInfo(alert_rule_id=str(r.id), is_active=r.is_active) for r in rules
            ]

    async def count_notifications_for_assessment(
        self, *, tenant_id: str, assessment_id: str
    ) -> int:
        async with self._db.session() as session:
            repo = SqlAlchemyNotificationRepository(session)
            notifications = await repo.list_by_assessment(
                TenantId.from_string(tenant_id), assessment_id
            )
            return len(notifications)


class CompositionRootDatasetReader:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_datasets(self, *, tenant_id: str) -> list[DatasetInfo]:
        async with self._db.session() as session:
            repo = SqlAlchemyDatasetRepository(session)
            datasets = await repo.list_catalog(TenantId.from_string(tenant_id))
            return [
                DatasetInfo(
                    dataset_id=str(d.id),
                    dataset_type=d.metadata.dataset_type.value,
                    provider=d.metadata.provider.value,
                    is_mlr_ready=DatasetReadinessTag.MLR_READY in d.readiness,
                    is_correlation_ready=DatasetReadinessTag.CORRELATION_READY in d.readiness,
                )
                for d in datasets
            ]


class CompositionRootReportReader:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_latest_report(
        self, *, tenant_id: str, assessment_id: str
    ) -> ReportInfo | None:
        async with self._db.session() as session:
            repo = SqlAlchemyReportRepository(session)
            report = await repo.get_latest(TenantId.from_string(tenant_id), assessment_id)
            if report is None:
                return None
            return ReportInfo(
                assessment_id=report.assessment_id,
                assessment_name=(
                    report.assessment_summary.name
                    if report.assessment_summary is not None
                    else None
                ),
                version=report.version,
                status=report.status.value,
                generated_at=report.generated_at,
            )

    async def list_latest_reports(self, *, tenant_id: str, limit: int) -> list[ReportInfo]:
        async with self._db.session() as session:
            repo = SqlAlchemyReportRepository(session)
            reports = await repo.list_latest_by_tenant(TenantId.from_string(tenant_id))
            return [
                ReportInfo(
                    assessment_id=r.assessment_id,
                    assessment_name=(
                        r.assessment_summary.name if r.assessment_summary is not None else None
                    ),
                    version=r.version,
                    status=r.status.value,
                    generated_at=r.generated_at,
                )
                for r in reports[:limit]
            ]
