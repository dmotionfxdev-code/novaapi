"""Pydantic request/response models — independent of the SQLAlchemy
models and domain entities (Architecture Redesign §9). Same pattern as
every prior context.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from georisk.contexts.prediction.domain.entities import PredictionRun


class RunPredictionRequest(BaseModel):
    variable_selection_id: str
    sampling_campaign_id: str
    method: str


class ModelMetadataResponse(BaseModel):
    model_type: str
    formula_version: str
    predictor_variable_codes: list[str]
    dependent_variable_code: str | None
    sample_size: int
    computed_at: datetime


class CorrelationPairResponse(BaseModel):
    variable_a: str
    variable_b: str
    coefficient: float
    sample_size: int


class RegressionVariableResponse(BaseModel):
    code: str
    coefficient: float
    standardized_coefficient: float
    standard_error: float
    t_statistic: float
    p_value: float


class PredictionRunResponse(BaseModel):
    id: str
    tenant_id: str
    assessment_id: str
    variable_selection_id: str
    sampling_campaign_id: str
    method: str
    version: int
    status: str
    error: str | None
    issued_by: str
    created_at: datetime
    model_metadata: ModelMetadataResponse | None
    correlation_pairs: list[CorrelationPairResponse] | None
    intercept: float | None
    variables: list[RegressionVariableResponse] | None
    r_squared: float | None
    adjusted_r_squared: float | None
    rmse: float | None
    mae: float | None

    @classmethod
    def from_domain(cls, run: PredictionRun) -> PredictionRunResponse:
        model_metadata = None
        if run.model_metadata is not None:
            model_metadata = ModelMetadataResponse(
                model_type=run.model_metadata.model_type.value,
                formula_version=run.model_metadata.formula_version,
                predictor_variable_codes=list(run.model_metadata.predictor_variable_codes),
                dependent_variable_code=run.model_metadata.dependent_variable_code,
                sample_size=run.model_metadata.sample_size,
                computed_at=run.model_metadata.computed_at,
            )

        correlation_pairs = None
        if run.correlation_result is not None:
            correlation_pairs = [
                CorrelationPairResponse(
                    variable_a=p.variable_a,
                    variable_b=p.variable_b,
                    coefficient=p.coefficient,
                    sample_size=p.sample_size,
                )
                for p in run.correlation_result.pairs
            ]

        intercept = r_squared = adjusted_r_squared = rmse = mae = None
        variables = None
        if run.regression_result is not None:
            reg = run.regression_result
            intercept = reg.intercept
            r_squared = reg.r_squared
            adjusted_r_squared = reg.adjusted_r_squared
            rmse = reg.rmse
            mae = reg.mae
            variables = [
                RegressionVariableResponse(
                    code=v.code,
                    coefficient=v.coefficient,
                    standardized_coefficient=v.standardized_coefficient,
                    standard_error=v.standard_error,
                    t_statistic=v.t_statistic,
                    p_value=v.p_value,
                )
                for v in reg.variables
            ]

        return cls(
            id=str(run.id),
            tenant_id=str(run.tenant_id),
            assessment_id=run.assessment_id,
            variable_selection_id=run.variable_selection_id,
            sampling_campaign_id=run.sampling_campaign_id,
            method=run.method.value,
            version=run.version,
            status=run.status.value,
            error=run.error,
            issued_by=run.issued_by,
            created_at=run.created_at,
            model_metadata=model_metadata,
            correlation_pairs=correlation_pairs,
            intercept=intercept,
            variables=variables,
            r_squared=r_squared,
            adjusted_r_squared=adjusted_r_squared,
            rmse=rmse,
            mae=mae,
        )


class PredictionRunListResponse(BaseModel):
    data: list[PredictionRunResponse]

    @classmethod
    def from_domain(cls, runs: list[PredictionRun]) -> PredictionRunListResponse:
        return cls(data=[PredictionRunResponse.from_domain(r) for r in runs])
