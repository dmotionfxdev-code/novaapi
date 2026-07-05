"""Composition-root glue wiring every upstream context Reporting reads
from — Assessment (+ Geospatial's AOI/SamplingCampaign), Analysis Engine's
``StageResult``, Prediction's ``PredictionRun``, Data Acquisition's
``Dataset`` catalog, and Validation's ``ValidationRun`` — into Reporting's
own read-only Protocol ports (``contexts/reporting/application/ports.py``).
Lives here, under ``api/``, deliberately outside every context involved —
the import-linter's peer-independence contract forbids any bounded context
from importing another, so the only place code needing all of these
contexts' repositories can legally live is a neutral composition layer, the
identical role ``api/workflow_stage_executors.py`` and
``api/prediction_ports.py`` already play.

Each reader opens its own session per call (``Database.session()``) rather
than sharing the caller's request-scoped session — the same "manages its
own transaction boundary" pattern every prior composition-root reader
already established, since these are read-only lookups against a
*different* aggregate than whatever transaction is currently open on the
caller's session.
"""

from __future__ import annotations

from georisk.contexts.analysis.domain.value_objects import StageType as AnalysisStageType
from georisk.contexts.analysis.infrastructure.repositories import SqlAlchemyStageResultRepository
from georisk.contexts.assessment.domain.value_objects import AssessmentId
from georisk.contexts.assessment.infrastructure.repositories import SqlAlchemyAssessmentRepository
from georisk.contexts.data_acquisition.domain.value_objects import DatasetReadinessTag
from georisk.contexts.data_acquisition.infrastructure.repositories import (
    SqlAlchemyDatasetRepository,
)
from georisk.contexts.geospatial.domain.value_objects import SamplingCampaignStatus
from georisk.contexts.geospatial.infrastructure.repositories import (
    SqlAlchemyAreaOfInterestRepository,
    SqlAlchemySamplingCampaignRepository,
)
from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.prediction.domain.entities import PredictionRun
from georisk.contexts.prediction.domain.value_objects import PredictionRunStatus
from georisk.contexts.prediction.infrastructure.repositories import (
    SqlAlchemyPredictionRunRepository,
)
from georisk.contexts.reporting.application.ports import (
    AssessmentInfo,
    DatasetInfo,
    PredictionRunInfo,
    RegressionInfo,
    StageResultInfo,
    ValidationRunInfo,
)
from georisk.contexts.validation.domain.value_objects import ValidationMode, ValidationRunStatus
from georisk.contexts.validation.infrastructure.repositories import (
    SqlAlchemyValidationRunRepository,
)
from georisk.db.session import Database

# The five core, gating stages every hazard strategy shares (Sprint 5/6) —
# never the three optional, non-gating WRRAS supporting-analysis stages
# (see ``application/ports.py``'s ``StageResultReader`` docstring).
_CORE_STAGE_TYPES = (
    AnalysisStageType.HAZARD,
    AnalysisStageType.EXPOSURE,
    AnalysisStageType.VULNERABILITY,
    AnalysisStageType.RISK,
    AnalysisStageType.RESILIENCE,
)


class CompositionRootAssessmentReader:
    """Implements Reporting's ``AssessmentReader`` port using Assessment's
    real repository directly, plus Geospatial's AOI/SamplingCampaign
    repositories folded in for convenience — this data genuinely exists
    (Sprint 2/7 built it)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_assessment_info(
        self, *, tenant_id: str, assessment_id: str
    ) -> AssessmentInfo | None:
        async with self._db.session() as session:
            assessment_repo = SqlAlchemyAssessmentRepository(session)
            assessment = await assessment_repo.get_by_id(AssessmentId.from_string(assessment_id))
            if assessment is None or str(assessment.tenant_id) != tenant_id:
                return None

            aoi_repo = SqlAlchemyAreaOfInterestRepository(session)
            aoi = await aoi_repo.get_active_for_assessment(assessment.tenant_id, assessment_id)

            campaign_repo = SqlAlchemySamplingCampaignRepository(session)
            campaigns = await campaign_repo.list_by_assessment(assessment.tenant_id, assessment_id)
            generated_campaigns = [
                c for c in campaigns if c.status is SamplingCampaignStatus.GENERATED
            ]
            latest_campaign = generated_campaigns[-1] if generated_campaigns else None

            return AssessmentInfo(
                assessment_id=str(assessment.id),
                name=assessment.name,
                hazard_type=assessment.hazard_type.value,
                status=assessment.status.value,
                created_at=assessment.created_at,
                aoi_name=aoi.metadata.name if aoi is not None else None,
                aoi_version=aoi.version if aoi is not None else None,
                aoi_area_m2=aoi.area_m2 if aoi is not None else None,
                sampling_campaign_name=(
                    latest_campaign.name if latest_campaign is not None else None
                ),
                sample_count=(
                    len(latest_campaign.sample_points) if latest_campaign is not None else None
                ),
            )


class CompositionRootStageResultReader:
    """Implements Reporting's ``StageResultReader`` port using Analysis
    Engine's real repository directly."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_latest_stage_results(
        self, *, tenant_id: str, assessment_id: str, hazard_type: str
    ) -> list[StageResultInfo]:
        async with self._db.session() as session:
            repo = SqlAlchemyStageResultRepository(session)
            tenant = TenantId.from_string(tenant_id)
            results = []
            for stage_type in _CORE_STAGE_TYPES:
                stage_result = await repo.get_latest(tenant, assessment_id, stage_type)
                if stage_result is None:
                    continue
                results.append(
                    StageResultInfo(
                        stage_type=stage_result.stage_type.value,
                        status=stage_result.status.value,
                        confidence_tier=(
                            stage_result.confidence_tier.value
                            if stage_result.confidence_tier is not None
                            else None
                        ),
                        formula_version=stage_result.formula_version,
                        strategy_version=stage_result.strategy_version,
                        indicators=(
                            stage_result.indicators.as_dict()
                            if stage_result.indicators is not None
                            else {}
                        ),
                        computed_at=stage_result.created_at,
                    )
                )
            return results


class CompositionRootPredictionReader:
    """Implements Reporting's ``PredictionReader`` port using Prediction's
    real repository directly."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_latest_prediction_runs(
        self, *, tenant_id: str, assessment_id: str
    ) -> list[PredictionRunInfo]:
        async with self._db.session() as session:
            repo = SqlAlchemyPredictionRunRepository(session)
            runs = await repo.list_by_assessment(TenantId.from_string(tenant_id), assessment_id)

            latest_by_method: dict[str, PredictionRun] = {}
            for run in runs:
                if run.status is not PredictionRunStatus.COMPLETED:
                    continue
                # ``runs`` is ordered newest-first (repository docstring) —
                # the first COMPLETED run seen per method is the latest one.
                latest_by_method.setdefault(run.method.value, run)

            infos = []
            for run in latest_by_method.values():
                regression: RegressionInfo | None = None
                if run.regression_result is not None:
                    coefficients = {v.code: v.coefficient for v in run.regression_result.variables}
                    regression = RegressionInfo(
                        intercept=run.regression_result.intercept,
                        coefficients=coefficients,
                        r_squared=run.regression_result.r_squared,
                        adjusted_r_squared=run.regression_result.adjusted_r_squared,
                        rmse=run.regression_result.rmse,
                        mae=run.regression_result.mae,
                    )
                correlation_pairs: tuple[tuple[str, str, float, int], ...] = ()
                if run.correlation_result is not None:
                    correlation_pairs = tuple(
                        (p.variable_a, p.variable_b, p.coefficient, p.sample_size)
                        for p in run.correlation_result.pairs
                    )
                infos.append(
                    PredictionRunInfo(
                        prediction_run_id=str(run.id),
                        method=run.method.value,
                        formula_version=(
                            run.model_metadata.formula_version
                            if run.model_metadata is not None
                            else ""
                        ),
                        sample_size=(
                            run.model_metadata.sample_size
                            if run.model_metadata is not None
                            else 0
                        ),
                        predictor_variable_codes=(
                            run.model_metadata.predictor_variable_codes
                            if run.model_metadata is not None
                            else ()
                        ),
                        dependent_variable_code=(
                            run.model_metadata.dependent_variable_code
                            if run.model_metadata is not None
                            else None
                        ),
                        correlation_pairs=correlation_pairs,
                        regression=regression,
                    )
                )
            return infos


class CompositionRootDatasetCatalogReader:
    """Implements Reporting's ``DatasetCatalogReader`` port using Data
    Acquisition's real repository directly."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_current_datasets(self, *, tenant_id: str) -> list[DatasetInfo]:
        async with self._db.session() as session:
            repo = SqlAlchemyDatasetRepository(session)
            datasets = await repo.list_catalog(TenantId.from_string(tenant_id))

            infos = []
            for dataset in datasets:
                latest_entry = dataset.provenance[-1] if dataset.provenance else None
                infos.append(
                    DatasetInfo(
                        dataset_id=str(dataset.id),
                        name=dataset.metadata.name,
                        version=dataset.version,
                        dataset_type=dataset.metadata.dataset_type.value,
                        provider=dataset.metadata.provider.value,
                        processing_method=dataset.metadata.processing_method.value,
                        is_mlr_ready=DatasetReadinessTag.MLR_READY in dataset.readiness,
                        is_correlation_ready=DatasetReadinessTag.CORRELATION_READY
                        in dataset.readiness,
                        provenance_entry_count=len(dataset.provenance),
                        latest_provenance_action=(
                            latest_entry.action if latest_entry is not None else None
                        ),
                        latest_provenance_at=(
                            latest_entry.timestamp if latest_entry is not None else None
                        ),
                    )
                )
            return infos


class CompositionRootValidationReader:
    """Implements Reporting's ``ValidationReader`` port using Validation's
    real repository directly."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_latest_validation(
        self, *, tenant_id: str, assessment_id: str
    ) -> ValidationRunInfo | None:
        async with self._db.session() as session:
            repo = SqlAlchemyValidationRunRepository(session)
            runs, _cursor, _has_more = await repo.list_by_assessment(
                TenantId.from_string(tenant_id), assessment_id, limit=1000, cursor=None
            )
            completed = [r for r in runs if r.status is ValidationRunStatus.COMPLETED]
            if not completed:
                return None
            # ``runs`` is ordered oldest-first (repository docstring) —
            # the last COMPLETED run is the latest one.
            latest = completed[-1]

            if latest.mode is ValidationMode.REGRESSION:
                regression = latest.regression_metrics
                return ValidationRunInfo(
                    validation_run_id=str(latest.id),
                    subject_type=latest.subject_type.value,
                    verdict=latest.verdict.value if latest.verdict is not None else None,
                    sample_size=regression.sample_size if regression is not None else 0,
                    computed_at=latest.created_at,
                    mode=latest.mode.value,
                    rmse=regression.rmse if regression is not None else None,
                    mae=regression.mae if regression is not None else None,
                    mse=regression.mse if regression is not None else None,
                    r_squared=regression.r_squared if regression is not None else None,
                    adjusted_r_squared=(
                        regression.adjusted_r_squared if regression is not None else None
                    ),
                )

            metrics = latest.metrics
            return ValidationRunInfo(
                validation_run_id=str(latest.id),
                subject_type=latest.subject_type.value,
                verdict=latest.verdict.value if latest.verdict is not None else None,
                sample_size=metrics.sample_size if metrics is not None else 0,
                computed_at=latest.created_at,
                mode=latest.mode.value,
                overall_accuracy=metrics.overall_accuracy if metrics is not None else None,
                precision=metrics.precision if metrics is not None else None,
                recall=metrics.recall if metrics is not None else None,
                f1_score=metrics.f1_score if metrics is not None else None,
                kappa=metrics.kappa if metrics is not None else None,
                auc=metrics.auc if metrics is not None else None,
            )
