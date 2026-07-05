"""Maps between the ``ValidationRun`` domain entity and its SQLAlchemy ORM
representation. Free functions, not methods on either side (same pattern
as every prior context).
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import datetime

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.validation.domain.entities import ValidationRun
from georisk.contexts.validation.domain.value_objects import (
    ConfusionMatrix,
    MetricSet,
    RegressionMetricSet,
    RegressionModelMetadata,
    RocPoint,
    SubjectType,
    ValidationMode,
    ValidationRunId,
    ValidationRunStatus,
    ValidationThresholds,
    Verdict,
)
from georisk.contexts.validation.infrastructure.models import ValidationRunModel


def _thresholds_to_json(thresholds: ValidationThresholds) -> dict:
    return {
        "min_overall_accuracy": thresholds.min_overall_accuracy,
        "min_precision": thresholds.min_precision,
        "min_recall": thresholds.min_recall,
        "min_f1_score": thresholds.min_f1_score,
        "min_auc": thresholds.min_auc,
        "max_rmse": thresholds.max_rmse,
        "max_mae": thresholds.max_mae,
        "min_r_squared": thresholds.min_r_squared,
        "min_adjusted_r_squared": thresholds.min_adjusted_r_squared,
    }


def _thresholds_from_json(data: dict) -> ValidationThresholds:
    return ValidationThresholds(
        min_overall_accuracy=data.get("min_overall_accuracy"),
        min_precision=data.get("min_precision"),
        min_recall=data.get("min_recall"),
        min_f1_score=data.get("min_f1_score"),
        min_auc=data.get("min_auc"),
        max_rmse=data.get("max_rmse"),
        max_mae=data.get("max_mae"),
        min_r_squared=data.get("min_r_squared"),
        min_adjusted_r_squared=data.get("min_adjusted_r_squared"),
    )


def _regression_metrics_to_json(metrics: RegressionMetricSet) -> dict:
    return {
        "sample_size": metrics.sample_size,
        "rmse": metrics.rmse,
        "mae": metrics.mae,
        "mse": metrics.mse,
        "r_squared": metrics.r_squared,
        "adjusted_r_squared": metrics.adjusted_r_squared,
    }


def _regression_metrics_from_json(data: dict) -> RegressionMetricSet:
    return RegressionMetricSet(
        sample_size=data["sample_size"],
        rmse=data["rmse"],
        mae=data["mae"],
        mse=data["mse"],
        r_squared=data["r_squared"],
        adjusted_r_squared=data["adjusted_r_squared"],
    )


def _model_metadata_to_json(metadata: RegressionModelMetadata) -> dict:
    return {
        "prediction_run_id": metadata.prediction_run_id,
        "method": metadata.method,
        "formula_version": metadata.formula_version,
        "predictor_variable_codes": list(metadata.predictor_variable_codes),
        "dependent_variable_code": metadata.dependent_variable_code,
        "sample_size": metadata.sample_size,
        "computed_at": metadata.computed_at.isoformat(),
    }


def _model_metadata_from_json(data: dict) -> RegressionModelMetadata:
    return RegressionModelMetadata(
        prediction_run_id=data["prediction_run_id"],
        method=data["method"],
        formula_version=data["formula_version"],
        predictor_variable_codes=tuple(data["predictor_variable_codes"]),
        dependent_variable_code=data.get("dependent_variable_code"),
        sample_size=data["sample_size"],
        computed_at=datetime.fromisoformat(data["computed_at"]),
    )


def _metrics_to_json(metrics: MetricSet) -> dict:
    cm = metrics.confusion_matrix
    return {
        "confusion_matrix": {"labels": list(cm.labels), "matrix": [list(row) for row in cm.matrix]},
        "sample_size": metrics.sample_size,
        "overall_accuracy": metrics.overall_accuracy,
        "precision": metrics.precision,
        "recall": metrics.recall,
        "specificity": metrics.specificity,
        "f1_score": metrics.f1_score,
        "kappa": metrics.kappa,
        "auc": metrics.auc,
        "optimal_threshold": metrics.optimal_threshold,
        "roc_points": [
            {"fpr": p.fpr, "tpr": p.tpr, "threshold": p.threshold} for p in metrics.roc_points
        ],
    }


def _metrics_from_json(data: dict) -> MetricSet:
    cm_data = data["confusion_matrix"]
    cm = ConfusionMatrix(
        labels=tuple(cm_data["labels"]),
        matrix=tuple(tuple(row) for row in cm_data["matrix"]),
    )
    return MetricSet(
        confusion_matrix=cm,
        sample_size=data["sample_size"],
        overall_accuracy=data.get("overall_accuracy"),
        precision=data.get("precision"),
        recall=data.get("recall"),
        specificity=data.get("specificity"),
        f1_score=data.get("f1_score"),
        kappa=data.get("kappa"),
        auc=data.get("auc"),
        optimal_threshold=data.get("optimal_threshold"),
        roc_points=tuple(
            RocPoint(fpr=p["fpr"], tpr=p["tpr"], threshold=p["threshold"])
            for p in data.get("roc_points", [])
        ),
    )


def validation_run_to_domain(model: ValidationRunModel) -> ValidationRun:
    return ValidationRun(
        id=ValidationRunId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        assessment_id=str(model.assessment_id),
        subject_id=model.subject_id,
        subject_type=SubjectType(model.subject_type),
        mode=ValidationMode(model.mode),
        status=ValidationRunStatus(model.status),
        thresholds=_thresholds_from_json(model.thresholds),
        metrics=_metrics_from_json(model.metrics) if model.metrics is not None else None,
        verdict=Verdict(model.verdict) if model.verdict is not None else None,
        error=model.error,
        issued_by=model.issued_by,
        created_at=model.created_at,
        regression_metrics=(
            _regression_metrics_from_json(model.regression_metrics)
            if model.regression_metrics is not None
            else None
        ),
        model_metadata=(
            _model_metadata_from_json(model.model_metadata)
            if model.model_metadata is not None
            else None
        ),
        version=model.version,
    )


def apply_validation_run_to_model(entity: ValidationRun, model: ValidationRunModel) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.assessment_id = uuid_module.UUID(entity.assessment_id)
    model.subject_id = entity.subject_id
    model.subject_type = entity.subject_type.value
    model.mode = entity.mode.value
    model.status = entity.status.value
    model.thresholds = _thresholds_to_json(entity.thresholds)
    model.metrics = _metrics_to_json(entity.metrics) if entity.metrics is not None else None
    model.regression_metrics = (
        _regression_metrics_to_json(entity.regression_metrics)
        if entity.regression_metrics is not None
        else None
    )
    model.model_metadata = (
        _model_metadata_to_json(entity.model_metadata)
        if entity.model_metadata is not None
        else None
    )
    model.verdict = entity.verdict.value if entity.verdict is not None else None
    model.error = entity.error
    model.issued_by = entity.issued_by
    model.created_at = entity.created_at
