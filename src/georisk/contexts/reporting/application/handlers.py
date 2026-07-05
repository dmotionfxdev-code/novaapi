"""``GenerateReportCommand``/``FinalizeReportCommand`` handlers.

``GenerateReportHandler`` is this context's ``ReportSnapshotBuilder``
(Application Layer §3): it gathers the confirmed Assessment plus every
optional upstream section via the injected reader ports, freezes them into
this context's own section VOs, persists a new ``DRAFT`` ``Report``
version, and appends the resulting event to the outbox. Never imports
anything from ``contexts.assessment``, ``contexts.analysis``,
``contexts.prediction``, ``contexts.data_acquisition``, or
``contexts.validation`` — the "Do not modify"/peer-independence
counterpart every prior context's handler already relies on.

``FinalizeReportHandler`` touches only Reporting's own aggregate — no
reader ports needed at all, since finalizing doesn't re-gather anything
(Sprint 9's brief doesn't ask for the fuller design doc's
``ValidationRun.verdict = FAIL`` override-guard or the "system-issued
``AdvanceAssessment`` reacting to ``ReportFinalized``" cross-context side
effect described in Domain Model §1 row 15 / Application Layer §3's
worked trace — both are natural future extensions, deliberately not built
here since neither was requested and the second would mean Reporting
mutating a peer aggregate, a bigger structural claim than "conformist
downstream reader").
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.reporting.application.commands import (
    FinalizeReportCommand,
    GenerateReportCommand,
)
from georisk.contexts.reporting.application.ports import (
    AssessmentInfo,
    AssessmentReader,
    DatasetCatalogReader,
    DatasetInfo,
    PredictionReader,
    PredictionRunInfo,
    StageResultInfo,
    StageResultReader,
    ValidationReader,
    ValidationRunInfo,
)
from georisk.contexts.reporting.domain.entities import Report
from georisk.contexts.reporting.domain.errors import (
    AssessmentNotAvailableError,
    ReportNotFoundError,
)
from georisk.contexts.reporting.domain.events import (
    ReportFinalized,
    ReportGenerated,
    ReportGenerationFailed,
)
from georisk.contexts.reporting.domain.value_objects import (
    AssessmentSummary,
    CorrelationPairSummary,
    DatasetProvenanceEntrySummary,
    PredictionSummary,
    RegressionSummary,
    ReportId,
    RiskSummarySection,
    StageFormulaVersion,
    StageSummary,
    ValidationSummary,
)
from georisk.contexts.reporting.infrastructure.repositories import SqlAlchemyReportRepository
from georisk.db.outbox_writer import append_event


def _build_assessment_summary(info: AssessmentInfo) -> AssessmentSummary:
    return AssessmentSummary(
        assessment_id=info.assessment_id,
        name=info.name,
        hazard_type=info.hazard_type,
        status=info.status,
        created_at=info.created_at,
        aoi_name=info.aoi_name,
        aoi_version=info.aoi_version,
        aoi_area_m2=info.aoi_area_m2,
        sampling_campaign_name=info.sampling_campaign_name,
        sample_count=info.sample_count,
    )


def _build_risk_summary(
    hazard_type: str, stage_results: list[StageResultInfo]
) -> tuple[RiskSummarySection | None, tuple[StageFormulaVersion, ...], str | None]:
    if not stage_results:
        return None, (), None

    stages = tuple(
        StageSummary(
            stage_type=r.stage_type,
            status=r.status,
            confidence_tier=r.confidence_tier,
            indicators=r.indicators,
            computed_at=r.computed_at,
        )
        for r in stage_results
    )
    formula_versions = tuple(
        StageFormulaVersion(stage_type=r.stage_type, formula_version=r.formula_version)
        for r in stage_results
    )
    strategy_version = next((r.strategy_version for r in stage_results if r.strategy_version), None)
    return (
        RiskSummarySection(hazard_type=hazard_type, stages=stages),
        formula_versions,
        strategy_version,
    )


def _build_predictor_summary(runs: list[PredictionRunInfo]) -> tuple[PredictionSummary, ...]:
    return tuple(
        PredictionSummary(
            prediction_run_id=run.prediction_run_id,
            method=run.method,
            formula_version=run.formula_version,
            sample_size=run.sample_size,
            predictor_variable_codes=run.predictor_variable_codes,
            dependent_variable_code=run.dependent_variable_code,
            correlation_pairs=tuple(
                CorrelationPairSummary(variable_a=a, variable_b=b, coefficient=c, sample_size=n)
                for a, b, c, n in run.correlation_pairs
            ),
            regression=(
                RegressionSummary(
                    intercept=run.regression.intercept,
                    coefficients=run.regression.coefficients,
                    r_squared=run.regression.r_squared,
                    adjusted_r_squared=run.regression.adjusted_r_squared,
                    rmse=run.regression.rmse,
                    mae=run.regression.mae,
                )
                if run.regression is not None
                else None
            ),
        )
        for run in runs
    )


def _build_dataset_provenance(
    datasets: list[DatasetInfo],
) -> tuple[DatasetProvenanceEntrySummary, ...]:
    return tuple(
        DatasetProvenanceEntrySummary(
            dataset_id=d.dataset_id,
            name=d.name,
            version=d.version,
            dataset_type=d.dataset_type,
            provider=d.provider,
            processing_method=d.processing_method,
            is_mlr_ready=d.is_mlr_ready,
            is_correlation_ready=d.is_correlation_ready,
            provenance_entry_count=d.provenance_entry_count,
            latest_provenance_action=d.latest_provenance_action,
            latest_provenance_at=d.latest_provenance_at,
        )
        for d in datasets
    )


def _build_validation_summary(info: ValidationRunInfo | None) -> ValidationSummary | None:
    if info is None:
        return None
    return ValidationSummary(
        validation_run_id=info.validation_run_id,
        subject_type=info.subject_type,
        verdict=info.verdict,
        sample_size=info.sample_size,
        computed_at=info.computed_at,
        mode=info.mode,
        overall_accuracy=info.overall_accuracy,
        precision=info.precision,
        recall=info.recall,
        f1_score=info.f1_score,
        kappa=info.kappa,
        auc=info.auc,
        rmse=info.rmse,
        mae=info.mae,
        mse=info.mse,
        r_squared=info.r_squared,
        adjusted_r_squared=info.adjusted_r_squared,
    )


class GenerateReportHandler:
    def __init__(
        self,
        session: AsyncSession,
        assessment_reader: AssessmentReader,
        stage_result_reader: StageResultReader,
        prediction_reader: PredictionReader,
        dataset_catalog_reader: DatasetCatalogReader,
        validation_reader: ValidationReader,
    ) -> None:
        self._session = session
        self._assessment_reader = assessment_reader
        self._stage_result_reader = stage_result_reader
        self._prediction_reader = prediction_reader
        self._dataset_catalog_reader = dataset_catalog_reader
        self._validation_reader = validation_reader
        self._repo = SqlAlchemyReportRepository(session)

    async def handle(self, command: GenerateReportCommand) -> Report:
        tenant_id = TenantId.from_string(command.tenant_id)
        event: ReportGenerated | ReportGenerationFailed

        try:
            assessment_info = await self._assessment_reader.get_assessment_info(
                tenant_id=command.tenant_id, assessment_id=command.assessment_id
            )
            if assessment_info is None:
                raise AssessmentNotAvailableError(
                    f"Assessment {command.assessment_id} not found"
                )

            assessment_summary = _build_assessment_summary(assessment_info)

            stage_results = await self._stage_result_reader.list_latest_stage_results(
                tenant_id=command.tenant_id,
                assessment_id=command.assessment_id,
                hazard_type=assessment_info.hazard_type,
            )
            risk_summary, formula_versions, strategy_version = _build_risk_summary(
                assessment_info.hazard_type, stage_results
            )

            prediction_runs = await self._prediction_reader.list_latest_prediction_runs(
                tenant_id=command.tenant_id, assessment_id=command.assessment_id
            )
            predictor_summary = _build_predictor_summary(prediction_runs)

            datasets = await self._dataset_catalog_reader.list_current_datasets(
                tenant_id=command.tenant_id
            )
            dataset_provenance = _build_dataset_provenance(datasets)

            validation_info = await self._validation_reader.get_latest_validation(
                tenant_id=command.tenant_id, assessment_id=command.assessment_id
            )
            validation_summary = _build_validation_summary(validation_info)

            version = await self._repo.next_version(tenant_id, command.assessment_id)
            result, event = Report.generate(
                tenant_id=tenant_id,
                assessment_id=command.assessment_id,
                version=version,
                assessment_summary=assessment_summary,
                risk_summary=risk_summary,
                predictor_summary=predictor_summary,
                dataset_provenance=dataset_provenance,
                validation_summary=validation_summary,
                formula_versions=formula_versions,
                strategy_version=strategy_version,
                issued_by=command.issued_by,
            )
        except Exception as exc:  # noqa: BLE001 — quarantining a resolution
            # failure (assessment not found/not visible) into a domain
            # fact (Report.FAILED), the same "isolate an untrusted
            # boundary" reasoning as every prior handler.
            version = await self._repo.next_version(tenant_id, command.assessment_id)
            result, event = Report.failed(
                tenant_id=tenant_id,
                assessment_id=command.assessment_id,
                version=version,
                error=str(exc),
                issued_by=command.issued_by,
            )

        await self._repo.save(result)
        await append_event(
            self._session,
            aggregate_type="Report",
            aggregate_id=str(result.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return result


class FinalizeReportHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = SqlAlchemyReportRepository(session)

    async def handle(self, command: FinalizeReportCommand) -> Report:
        tenant_id = TenantId.from_string(command.tenant_id)
        report = await self._repo.get_by_id(ReportId.from_string(command.report_id))
        if report is None or report.tenant_id != tenant_id:
            raise ReportNotFoundError(f"Report {command.report_id} not found")

        event: ReportFinalized = report.finalize(finalized_by=command.finalized_by)

        await self._repo.save(report)
        await append_event(
            self._session,
            aggregate_type="Report",
            aggregate_id=str(report.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )
        await self._session.commit()
        return report
