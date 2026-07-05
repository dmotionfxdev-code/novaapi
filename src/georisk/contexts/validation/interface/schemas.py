"""Pydantic request/response models — independent of the SQLAlchemy models
and domain entities (Architecture Redesign §9). Same pattern as every
prior context.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from georisk.contexts.validation.domain.entities import ValidationRun
from georisk.contexts.validation.domain.value_objects import (
    MetricSet,
    RegressionMetricSet,
    RegressionModelMetadata,
)
from georisk.shared_kernel.types import CursorPage


class RunValidationRequest(BaseModel):
    subject_id: str = Field(min_length=1, max_length=200)
    subject_type: str


class RunRegressionValidationRequest(BaseModel):
    subject_id: str = Field(min_length=1, max_length=200)


class ConfusionMatrixResponse(BaseModel):
    labels: list[str]
    matrix: list[list[int]]


class RocPointResponse(BaseModel):
    fpr: float
    tpr: float
    threshold: float


class MetricSetResponse(BaseModel):
    confusion_matrix: ConfusionMatrixResponse
    sample_size: int
    overall_accuracy: float | None
    precision: float | None
    recall: float | None
    specificity: float | None
    f1_score: float | None
    kappa: float | None
    auc: float | None
    optimal_threshold: float | None
    roc_points: list[RocPointResponse]

    @classmethod
    def from_domain(cls, metrics: MetricSet) -> MetricSetResponse:
        return cls(
            confusion_matrix=ConfusionMatrixResponse(
                labels=list(metrics.confusion_matrix.labels),
                matrix=[list(row) for row in metrics.confusion_matrix.matrix],
            ),
            sample_size=metrics.sample_size,
            overall_accuracy=metrics.overall_accuracy,
            precision=metrics.precision,
            recall=metrics.recall,
            specificity=metrics.specificity,
            f1_score=metrics.f1_score,
            kappa=metrics.kappa,
            auc=metrics.auc,
            optimal_threshold=metrics.optimal_threshold,
            roc_points=[
                RocPointResponse(fpr=p.fpr, tpr=p.tpr, threshold=p.threshold)
                for p in metrics.roc_points
            ],
        )


class RegressionMetricSetResponse(BaseModel):
    sample_size: int
    rmse: float
    mae: float
    mse: float
    r_squared: float
    adjusted_r_squared: float

    @classmethod
    def from_domain(cls, metrics: RegressionMetricSet) -> RegressionMetricSetResponse:
        return cls(
            sample_size=metrics.sample_size,
            rmse=metrics.rmse,
            mae=metrics.mae,
            mse=metrics.mse,
            r_squared=metrics.r_squared,
            adjusted_r_squared=metrics.adjusted_r_squared,
        )


class RegressionModelMetadataResponse(BaseModel):
    prediction_run_id: str
    method: str
    formula_version: str
    predictor_variable_codes: list[str]
    dependent_variable_code: str | None
    sample_size: int
    computed_at: datetime

    @classmethod
    def from_domain(cls, metadata: RegressionModelMetadata) -> RegressionModelMetadataResponse:
        return cls(
            prediction_run_id=metadata.prediction_run_id,
            method=metadata.method,
            formula_version=metadata.formula_version,
            predictor_variable_codes=list(metadata.predictor_variable_codes),
            dependent_variable_code=metadata.dependent_variable_code,
            sample_size=metadata.sample_size,
            computed_at=metadata.computed_at,
        )


class ValidationRunResponse(BaseModel):
    id: str
    tenant_id: str
    assessment_id: str
    subject_id: str
    subject_type: str
    mode: str
    status: str
    verdict: str | None
    error: str | None
    issued_by: str
    created_at: datetime
    metrics: MetricSetResponse | None
    regression_metrics: RegressionMetricSetResponse | None
    model_metadata: RegressionModelMetadataResponse | None

    @classmethod
    def from_domain(cls, run: ValidationRun) -> ValidationRunResponse:
        return cls(
            id=str(run.id),
            tenant_id=str(run.tenant_id),
            assessment_id=run.assessment_id,
            subject_id=run.subject_id,
            subject_type=run.subject_type.value,
            mode=run.mode.value,
            status=run.status.value,
            verdict=run.verdict.value if run.verdict is not None else None,
            error=run.error,
            issued_by=run.issued_by,
            created_at=run.created_at,
            metrics=MetricSetResponse.from_domain(run.metrics) if run.metrics is not None else None,
            regression_metrics=(
                RegressionMetricSetResponse.from_domain(run.regression_metrics)
                if run.regression_metrics is not None
                else None
            ),
            model_metadata=(
                RegressionModelMetadataResponse.from_domain(run.model_metadata)
                if run.model_metadata is not None
                else None
            ),
        )


class ValidationRunListResponse(BaseModel):
    data: list[ValidationRunResponse]
    next_cursor: str | None
    has_more: bool

    @classmethod
    def from_page(cls, page: CursorPage[ValidationRun]) -> ValidationRunListResponse:
        return cls(
            data=[ValidationRunResponse.from_domain(r) for r in page.items],
            next_cursor=page.next_cursor,
            has_more=page.has_more,
        )
