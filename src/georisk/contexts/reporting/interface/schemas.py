"""Pydantic request/response models — independent of the SQLAlchemy models
and domain entities (Architecture Redesign §9). Same pattern as every
prior context. "PDF-ready report structure" (Sprint 9 requirement #8) is
satisfied by this shape itself: an ordered set of self-contained sections
a future PDF/DOCX renderer can walk one at a time, without that renderer
existing yet (explicitly out of scope this sprint).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from georisk.contexts.reporting.domain.entities import Report


class AssessmentSummaryResponse(BaseModel):
    assessment_id: str
    name: str
    hazard_type: str
    status: str
    created_at: datetime
    aoi_name: str | None
    aoi_version: int | None
    aoi_area_m2: float | None
    sampling_campaign_name: str | None
    sample_count: int | None


class StageSummaryResponse(BaseModel):
    stage_type: str
    status: str
    confidence_tier: str | None
    indicators: dict[str, float]
    computed_at: datetime


class RiskSummaryResponse(BaseModel):
    hazard_type: str
    stages: list[StageSummaryResponse]


class FormulaVersionResponse(BaseModel):
    stage_type: str
    formula_version: str | None


class CorrelationPairResponse(BaseModel):
    variable_a: str
    variable_b: str
    coefficient: float
    sample_size: int


class RegressionSummaryResponse(BaseModel):
    intercept: float
    coefficients: dict[str, float]
    r_squared: float
    adjusted_r_squared: float
    rmse: float
    mae: float


class PredictionSummaryResponse(BaseModel):
    prediction_run_id: str
    method: str
    formula_version: str
    sample_size: int
    predictor_variable_codes: list[str]
    dependent_variable_code: str | None
    correlation_pairs: list[CorrelationPairResponse]
    regression: RegressionSummaryResponse | None


class DatasetProvenanceEntryResponse(BaseModel):
    dataset_id: str
    name: str
    version: int
    dataset_type: str
    provider: str
    processing_method: str
    is_mlr_ready: bool
    is_correlation_ready: bool
    provenance_entry_count: int
    latest_provenance_action: str | None
    latest_provenance_at: datetime | None


class ValidationSummaryResponse(BaseModel):
    validation_run_id: str
    subject_type: str
    verdict: str | None
    sample_size: int
    mode: str
    overall_accuracy: float | None
    precision: float | None
    recall: float | None
    f1_score: float | None
    kappa: float | None
    auc: float | None
    rmse: float | None
    mae: float | None
    mse: float | None
    r_squared: float | None
    adjusted_r_squared: float | None
    computed_at: datetime


class ReportResponse(BaseModel):
    id: str
    tenant_id: str
    assessment_id: str
    version: int
    status: str
    generated_at: datetime
    issued_by: str
    error: str | None
    finalized_by: str | None
    finalized_at: datetime | None
    strategy_version: str | None
    formula_versions: list[FormulaVersionResponse]
    assessment_summary: AssessmentSummaryResponse | None
    risk_summary: RiskSummaryResponse | None
    predictor_summary: list[PredictionSummaryResponse]
    dataset_provenance: list[DatasetProvenanceEntryResponse]
    validation_summary: ValidationSummaryResponse | None

    @classmethod
    def from_domain(cls, report: Report) -> ReportResponse:
        assessment_summary = None
        if report.assessment_summary is not None:
            s = report.assessment_summary
            assessment_summary = AssessmentSummaryResponse(
                assessment_id=s.assessment_id,
                name=s.name,
                hazard_type=s.hazard_type,
                status=s.status,
                created_at=s.created_at,
                aoi_name=s.aoi_name,
                aoi_version=s.aoi_version,
                aoi_area_m2=s.aoi_area_m2,
                sampling_campaign_name=s.sampling_campaign_name,
                sample_count=s.sample_count,
            )

        risk_summary = None
        if report.risk_summary is not None:
            risk_summary = RiskSummaryResponse(
                hazard_type=report.risk_summary.hazard_type,
                stages=[
                    StageSummaryResponse(
                        stage_type=stage.stage_type,
                        status=stage.status,
                        confidence_tier=stage.confidence_tier,
                        indicators=stage.indicators,
                        computed_at=stage.computed_at,
                    )
                    for stage in report.risk_summary.stages
                ],
            )

        predictor_summary = [
            PredictionSummaryResponse(
                prediction_run_id=p.prediction_run_id,
                method=p.method,
                formula_version=p.formula_version,
                sample_size=p.sample_size,
                predictor_variable_codes=list(p.predictor_variable_codes),
                dependent_variable_code=p.dependent_variable_code,
                correlation_pairs=[
                    CorrelationPairResponse(
                        variable_a=pair.variable_a,
                        variable_b=pair.variable_b,
                        coefficient=pair.coefficient,
                        sample_size=pair.sample_size,
                    )
                    for pair in p.correlation_pairs
                ],
                regression=(
                    RegressionSummaryResponse(
                        intercept=p.regression.intercept,
                        coefficients=p.regression.coefficients,
                        r_squared=p.regression.r_squared,
                        adjusted_r_squared=p.regression.adjusted_r_squared,
                        rmse=p.regression.rmse,
                        mae=p.regression.mae,
                    )
                    if p.regression is not None
                    else None
                ),
            )
            for p in report.predictor_summary
        ]

        dataset_provenance = [
            DatasetProvenanceEntryResponse(
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
            for d in report.dataset_provenance
        ]

        validation_summary = None
        if report.validation_summary is not None:
            v = report.validation_summary
            validation_summary = ValidationSummaryResponse(
                validation_run_id=v.validation_run_id,
                subject_type=v.subject_type,
                verdict=v.verdict,
                sample_size=v.sample_size,
                mode=v.mode,
                overall_accuracy=v.overall_accuracy,
                precision=v.precision,
                recall=v.recall,
                f1_score=v.f1_score,
                kappa=v.kappa,
                auc=v.auc,
                rmse=v.rmse,
                mae=v.mae,
                mse=v.mse,
                r_squared=v.r_squared,
                adjusted_r_squared=v.adjusted_r_squared,
                computed_at=v.computed_at,
            )

        return cls(
            id=str(report.id),
            tenant_id=str(report.tenant_id),
            assessment_id=report.assessment_id,
            version=report.version,
            status=report.status.value,
            generated_at=report.generated_at,
            issued_by=report.issued_by,
            error=report.error,
            finalized_by=report.finalized_by,
            finalized_at=report.finalized_at,
            strategy_version=report.strategy_version,
            formula_versions=[
                FormulaVersionResponse(stage_type=f.stage_type, formula_version=f.formula_version)
                for f in report.formula_versions
            ],
            assessment_summary=assessment_summary,
            risk_summary=risk_summary,
            predictor_summary=predictor_summary,
            dataset_provenance=dataset_provenance,
            validation_summary=validation_summary,
        )


class ReportListResponse(BaseModel):
    data: list[ReportResponse]

    @classmethod
    def from_domain(cls, reports: list[Report]) -> ReportListResponse:
        return cls(data=[ReportResponse.from_domain(r) for r in reports])
