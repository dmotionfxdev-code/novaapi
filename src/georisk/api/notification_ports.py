"""Composition-root glue wiring Assessment, Analysis Engine, Prediction,
and Validation into Notification's own read-only Protocol ports
(``contexts/notification/application/ports.py``). Lives here, under
``api/``, deliberately outside every context involved — the import-
linter's peer-independence contract forbids any bounded context from
importing another, so the only place code needing all of these contexts'
repositories can legally live is a neutral composition layer, the
identical role ``api/reporting_ports.py``/``api/validation_ports.py``
already play.

Each reader opens its own session per call (``Database.session()``)
rather than sharing the caller's request-scoped session — the same
"manages its own transaction boundary" pattern every prior composition-
root reader already established.
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.value_objects import StageType as AnalysisStageType
from georisk.contexts.analysis.infrastructure.repositories import SqlAlchemyStageResultRepository
from georisk.contexts.assessment.domain.value_objects import AssessmentId
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.notification.application.ports import AssessmentInfo
from georisk.contexts.notification.domain.value_objects import AlertSubjectType
from georisk.contexts.prediction.domain.value_objects import PredictionRunStatus
from georisk.contexts.prediction.infrastructure.repositories import (
    SqlAlchemyPredictionRunRepository,
)
from georisk.contexts.validation.domain.value_objects import ValidationRunStatus
from georisk.contexts.validation.infrastructure.repositories import (
    SqlAlchemyValidationRunRepository,
)
from georisk.db.session import Database


class CompositionRootAssessmentReader:
    """Implements Notification's ``AssessmentReader`` port using
    Assessment's real repository directly — read-only (a ``get_by_id``
    call and nothing else), so "no changes to Assessment" holds
    structurally: this module has no path to any Assessment command."""

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
            )


class CompositionRootAlertMetricReader:
    """Implements Notification's ``AlertMetricReader`` port by branching
    on ``subject_type`` and reading each upstream context's real
    repository directly — Analysis Engine's ``StageResult`` (FRI/WRI-style
    alerts), Prediction's ``PredictionRun`` regression fit (RMSE/R²-style
    alerts), or Validation's ``ValidationRun`` metrics (either
    classification or regression, whichever is populated)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_metric_value(
        self,
        *,
        tenant_id: str,
        assessment_id: str,
        subject_type: str,
        stage_type: str | None,
        metric_code: str,
    ) -> float | None:
        subject = AlertSubjectType(subject_type)
        if subject is AlertSubjectType.STAGE_RESULT:
            return await self._read_stage_result_metric(
                tenant_id, assessment_id, stage_type, metric_code
            )
        if subject is AlertSubjectType.PREDICTION:
            return await self._read_prediction_metric(tenant_id, assessment_id, metric_code)
        return await self._read_validation_metric(tenant_id, assessment_id, metric_code)

    async def _read_stage_result_metric(
        self, tenant_id: str, assessment_id: str, stage_type: str | None, metric_code: str
    ) -> float | None:
        if not stage_type:
            return None
        try:
            resolved_stage_type = AnalysisStageType(stage_type)
        except ValueError:
            # A misconfigured rule's stage_type doesn't match any known
            # stage — the Early Warning Engine treats this exactly like
            # "no evidence yet," never a crash.
            return None

        async with self._db.session() as session:
            repo = SqlAlchemyStageResultRepository(session)
            stage_result = await repo.get_latest(
                TenantId.from_string(tenant_id), assessment_id, resolved_stage_type
            )
            if stage_result is None or stage_result.indicators is None:
                return None
            return stage_result.indicators.value(metric_code)

    async def _read_prediction_metric(
        self, tenant_id: str, assessment_id: str, metric_code: str
    ) -> float | None:
        async with self._db.session() as session:
            repo = SqlAlchemyPredictionRunRepository(session)
            runs = await repo.list_by_assessment(TenantId.from_string(tenant_id), assessment_id)
            for run in runs:  # newest-first (repository docstring)
                if run.status is not PredictionRunStatus.COMPLETED:
                    continue
                if run.regression_result is None:
                    continue
                return getattr(run.regression_result, metric_code, None)
            return None

    async def _read_validation_metric(
        self, tenant_id: str, assessment_id: str, metric_code: str
    ) -> float | None:
        async with self._db.session() as session:
            repo = SqlAlchemyValidationRunRepository(session)
            runs, _cursor, _has_more = await repo.list_by_assessment(
                TenantId.from_string(tenant_id), assessment_id, limit=1000, cursor=None
            )
            completed = [r for r in runs if r.status is ValidationRunStatus.COMPLETED]
            if not completed:
                return None
            latest = completed[-1]  # oldest-first (repository docstring)
            if latest.regression_metrics is not None:
                value = getattr(latest.regression_metrics, metric_code, None)
                if value is not None:
                    return value
            if latest.metrics is not None:
                return getattr(latest.metrics, metric_code, None)
            return None
