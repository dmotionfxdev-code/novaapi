"""Maps between the ``Report`` domain entity and its SQLAlchemy ORM
representation. Free functions, not methods on either side (same pattern
as every prior context).
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import datetime

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.reporting.domain.entities import Report
from georisk.contexts.reporting.domain.value_objects import (
    AssessmentSummary,
    CorrelationPairSummary,
    DatasetProvenanceEntrySummary,
    PredictionSummary,
    RegressionSummary,
    ReportId,
    ReportStatus,
    RiskSummarySection,
    StageFormulaVersion,
    StageSummary,
    ValidationSummary,
)
from georisk.contexts.reporting.infrastructure.models import ReportModel


def _assessment_summary_to_json(summary: AssessmentSummary) -> dict:
    return {
        "assessment_id": summary.assessment_id,
        "name": summary.name,
        "hazard_type": summary.hazard_type,
        "status": summary.status,
        "created_at": summary.created_at.isoformat(),
        "aoi_name": summary.aoi_name,
        "aoi_version": summary.aoi_version,
        "aoi_area_m2": summary.aoi_area_m2,
        "sampling_campaign_name": summary.sampling_campaign_name,
        "sample_count": summary.sample_count,
    }


def _assessment_summary_from_json(data: dict) -> AssessmentSummary:
    return AssessmentSummary(
        assessment_id=data["assessment_id"],
        name=data["name"],
        hazard_type=data["hazard_type"],
        status=data["status"],
        created_at=datetime.fromisoformat(data["created_at"]),
        aoi_name=data.get("aoi_name"),
        aoi_version=data.get("aoi_version"),
        aoi_area_m2=data.get("aoi_area_m2"),
        sampling_campaign_name=data.get("sampling_campaign_name"),
        sample_count=data.get("sample_count"),
    )


def _stage_summary_to_json(stage: StageSummary) -> dict:
    return {
        "stage_type": stage.stage_type,
        "status": stage.status,
        "confidence_tier": stage.confidence_tier,
        "indicators": stage.indicators,
        "computed_at": stage.computed_at.isoformat(),
    }


def _stage_summary_from_json(data: dict) -> StageSummary:
    return StageSummary(
        stage_type=data["stage_type"],
        status=data["status"],
        confidence_tier=data.get("confidence_tier"),
        indicators=data["indicators"],
        computed_at=datetime.fromisoformat(data["computed_at"]),
    )


def _risk_summary_to_json(section: RiskSummarySection) -> dict:
    return {
        "hazard_type": section.hazard_type,
        "stages": [_stage_summary_to_json(s) for s in section.stages],
    }


def _risk_summary_from_json(data: dict) -> RiskSummarySection:
    return RiskSummarySection(
        hazard_type=data["hazard_type"],
        stages=tuple(_stage_summary_from_json(s) for s in data["stages"]),
    )


def _prediction_summary_to_json(summary: PredictionSummary) -> dict:
    return {
        "prediction_run_id": summary.prediction_run_id,
        "method": summary.method,
        "formula_version": summary.formula_version,
        "sample_size": summary.sample_size,
        "predictor_variable_codes": list(summary.predictor_variable_codes),
        "dependent_variable_code": summary.dependent_variable_code,
        "correlation_pairs": [
            {
                "variable_a": p.variable_a,
                "variable_b": p.variable_b,
                "coefficient": p.coefficient,
                "sample_size": p.sample_size,
            }
            for p in summary.correlation_pairs
        ],
        "regression": (
            {
                "intercept": summary.regression.intercept,
                "coefficients": summary.regression.coefficients,
                "r_squared": summary.regression.r_squared,
                "adjusted_r_squared": summary.regression.adjusted_r_squared,
                "rmse": summary.regression.rmse,
                "mae": summary.regression.mae,
            }
            if summary.regression is not None
            else None
        ),
    }


def _prediction_summary_from_json(data: dict) -> PredictionSummary:
    regression_data = data.get("regression")
    return PredictionSummary(
        prediction_run_id=data["prediction_run_id"],
        method=data["method"],
        formula_version=data["formula_version"],
        sample_size=data["sample_size"],
        predictor_variable_codes=tuple(data["predictor_variable_codes"]),
        dependent_variable_code=data.get("dependent_variable_code"),
        correlation_pairs=tuple(
            CorrelationPairSummary(
                variable_a=p["variable_a"],
                variable_b=p["variable_b"],
                coefficient=p["coefficient"],
                sample_size=p["sample_size"],
            )
            for p in data.get("correlation_pairs", [])
        ),
        regression=(
            RegressionSummary(
                intercept=regression_data["intercept"],
                coefficients=regression_data["coefficients"],
                r_squared=regression_data["r_squared"],
                adjusted_r_squared=regression_data["adjusted_r_squared"],
                rmse=regression_data["rmse"],
                mae=regression_data["mae"],
            )
            if regression_data is not None
            else None
        ),
    )


def _dataset_provenance_entry_to_json(entry: DatasetProvenanceEntrySummary) -> dict:
    return {
        "dataset_id": entry.dataset_id,
        "name": entry.name,
        "version": entry.version,
        "dataset_type": entry.dataset_type,
        "provider": entry.provider,
        "processing_method": entry.processing_method,
        "is_mlr_ready": entry.is_mlr_ready,
        "is_correlation_ready": entry.is_correlation_ready,
        "provenance_entry_count": entry.provenance_entry_count,
        "latest_provenance_action": entry.latest_provenance_action,
        "latest_provenance_at": (
            entry.latest_provenance_at.isoformat()
            if entry.latest_provenance_at is not None
            else None
        ),
    }


def _dataset_provenance_entry_from_json(data: dict) -> DatasetProvenanceEntrySummary:
    latest_at = data.get("latest_provenance_at")
    return DatasetProvenanceEntrySummary(
        dataset_id=data["dataset_id"],
        name=data["name"],
        version=data["version"],
        dataset_type=data["dataset_type"],
        provider=data["provider"],
        processing_method=data["processing_method"],
        is_mlr_ready=data["is_mlr_ready"],
        is_correlation_ready=data["is_correlation_ready"],
        provenance_entry_count=data["provenance_entry_count"],
        latest_provenance_action=data.get("latest_provenance_action"),
        latest_provenance_at=datetime.fromisoformat(latest_at) if latest_at is not None else None,
    )


def _validation_summary_to_json(summary: ValidationSummary) -> dict:
    return {
        "validation_run_id": summary.validation_run_id,
        "subject_type": summary.subject_type,
        "verdict": summary.verdict,
        "sample_size": summary.sample_size,
        "mode": summary.mode,
        "overall_accuracy": summary.overall_accuracy,
        "precision": summary.precision,
        "recall": summary.recall,
        "f1_score": summary.f1_score,
        "kappa": summary.kappa,
        "auc": summary.auc,
        "rmse": summary.rmse,
        "mae": summary.mae,
        "mse": summary.mse,
        "r_squared": summary.r_squared,
        "adjusted_r_squared": summary.adjusted_r_squared,
        "computed_at": summary.computed_at.isoformat(),
    }


def _validation_summary_from_json(data: dict) -> ValidationSummary:
    return ValidationSummary(
        validation_run_id=data["validation_run_id"],
        subject_type=data["subject_type"],
        verdict=data.get("verdict"),
        sample_size=data["sample_size"],
        mode=data.get("mode", "CLASSIFICATION"),
        overall_accuracy=data.get("overall_accuracy"),
        precision=data.get("precision"),
        recall=data.get("recall"),
        f1_score=data.get("f1_score"),
        kappa=data.get("kappa"),
        auc=data.get("auc"),
        rmse=data.get("rmse"),
        mae=data.get("mae"),
        mse=data.get("mse"),
        r_squared=data.get("r_squared"),
        adjusted_r_squared=data.get("adjusted_r_squared"),
        computed_at=datetime.fromisoformat(data["computed_at"]),
    )


def _formula_version_to_json(entry: StageFormulaVersion) -> dict:
    return {"stage_type": entry.stage_type, "formula_version": entry.formula_version}


def _formula_version_from_json(data: dict) -> StageFormulaVersion:
    return StageFormulaVersion(
        stage_type=data["stage_type"], formula_version=data.get("formula_version")
    )


def report_to_domain(model: ReportModel) -> Report:
    return Report(
        id=ReportId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        assessment_id=str(model.assessment_id),
        version=model.version,
        status=ReportStatus(model.status),
        generated_at=model.generated_at,
        issued_by=model.issued_by,
        assessment_summary=(
            _assessment_summary_from_json(model.assessment_summary)
            if model.assessment_summary is not None
            else None
        ),
        risk_summary=(
            _risk_summary_from_json(model.risk_summary) if model.risk_summary is not None else None
        ),
        predictor_summary=tuple(
            _prediction_summary_from_json(p) for p in (model.predictor_summary or [])
        ),
        dataset_provenance=tuple(
            _dataset_provenance_entry_from_json(d) for d in (model.dataset_provenance or [])
        ),
        validation_summary=(
            _validation_summary_from_json(model.validation_summary)
            if model.validation_summary is not None
            else None
        ),
        formula_versions=tuple(
            _formula_version_from_json(f) for f in (model.formula_versions or [])
        ),
        strategy_version=model.strategy_version,
        error=model.error,
        finalized_by=model.finalized_by,
        finalized_at=model.finalized_at,
    )


def apply_report_to_model(entity: Report, model: ReportModel) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.assessment_id = uuid_module.UUID(entity.assessment_id)
    model.version = entity.version
    model.status = entity.status.value
    model.generated_at = entity.generated_at
    model.issued_by = entity.issued_by
    model.assessment_summary = (
        _assessment_summary_to_json(entity.assessment_summary)
        if entity.assessment_summary is not None
        else None
    )
    model.risk_summary = (
        _risk_summary_to_json(entity.risk_summary) if entity.risk_summary is not None else None
    )
    model.predictor_summary = [
        _prediction_summary_to_json(p) for p in entity.predictor_summary
    ] or None
    model.dataset_provenance = [
        _dataset_provenance_entry_to_json(d) for d in entity.dataset_provenance
    ] or None
    model.validation_summary = (
        _validation_summary_to_json(entity.validation_summary)
        if entity.validation_summary is not None
        else None
    )
    model.formula_versions = [
        _formula_version_to_json(f) for f in entity.formula_versions
    ] or None
    model.strategy_version = entity.strategy_version
    model.error = entity.error
    model.finalized_by = entity.finalized_by
    model.finalized_at = entity.finalized_at
