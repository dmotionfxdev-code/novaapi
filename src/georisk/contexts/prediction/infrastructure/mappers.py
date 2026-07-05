"""Maps between the ``PredictionRun`` domain entity and its SQLAlchemy
ORM representation. Free functions, not methods on either side (same
pattern as every prior context).
"""

from __future__ import annotations

import uuid as uuid_module
from datetime import datetime

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.prediction.domain.entities import PredictionRun
from georisk.contexts.prediction.domain.value_objects import (
    CorrelationPair,
    CorrelationResult,
    ModelMetadata,
    PredictionMethod,
    PredictionRunId,
    PredictionRunStatus,
    RegressionResult,
    RegressionVariableResult,
)
from georisk.contexts.prediction.infrastructure.models import PredictionRunModel


def _model_metadata_to_json(metadata: ModelMetadata) -> dict:
    return {
        "model_type": metadata.model_type.value,
        "formula_version": metadata.formula_version,
        "predictor_variable_codes": list(metadata.predictor_variable_codes),
        "dependent_variable_code": metadata.dependent_variable_code,
        "sample_size": metadata.sample_size,
        "computed_at": metadata.computed_at.isoformat(),
    }


def _model_metadata_from_json(data: dict) -> ModelMetadata:
    return ModelMetadata(
        model_type=PredictionMethod(data["model_type"]),
        formula_version=data["formula_version"],
        predictor_variable_codes=tuple(data["predictor_variable_codes"]),
        dependent_variable_code=data.get("dependent_variable_code"),
        sample_size=data["sample_size"],
        computed_at=datetime.fromisoformat(data["computed_at"]),
    )


def _correlation_result_to_json(result: CorrelationResult) -> dict:
    return {
        "pairs": [
            {
                "variable_a": p.variable_a,
                "variable_b": p.variable_b,
                "coefficient": p.coefficient,
                "sample_size": p.sample_size,
            }
            for p in result.pairs
        ]
    }


def _correlation_result_from_json(data: dict) -> CorrelationResult:
    return CorrelationResult(
        pairs=tuple(
            CorrelationPair(
                variable_a=p["variable_a"],
                variable_b=p["variable_b"],
                coefficient=p["coefficient"],
                sample_size=p["sample_size"],
            )
            for p in data["pairs"]
        )
    )


def _regression_result_to_json(result: RegressionResult) -> dict:
    return {
        "intercept": result.intercept,
        "variables": [
            {
                "code": v.code,
                "coefficient": v.coefficient,
                "standardized_coefficient": v.standardized_coefficient,
                "standard_error": v.standard_error,
                "t_statistic": v.t_statistic,
                "p_value": v.p_value,
            }
            for v in result.variables
        ],
        "r_squared": result.r_squared,
        "adjusted_r_squared": result.adjusted_r_squared,
        "rmse": result.rmse,
        "mae": result.mae,
        "f_statistic": result.f_statistic,
        "mse": result.mse,
    }


def _regression_result_from_json(data: dict) -> RegressionResult:
    return RegressionResult(
        intercept=data["intercept"],
        variables=tuple(
            RegressionVariableResult(
                code=v["code"],
                coefficient=v["coefficient"],
                standardized_coefficient=v["standardized_coefficient"],
                standard_error=v["standard_error"],
                t_statistic=v["t_statistic"],
                p_value=v["p_value"],
            )
            for v in data["variables"]
        ),
        r_squared=data["r_squared"],
        adjusted_r_squared=data["adjusted_r_squared"],
        rmse=data["rmse"],
        mae=data["mae"],
        f_statistic=data["f_statistic"],
        mse=data["mse"],
    )


def prediction_run_to_domain(model: PredictionRunModel) -> PredictionRun:
    return PredictionRun(
        id=PredictionRunId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        assessment_id=str(model.assessment_id),
        variable_selection_id=str(model.variable_selection_id),
        sampling_campaign_id=str(model.sampling_campaign_id),
        method=PredictionMethod(model.method),
        version=model.version,
        status=PredictionRunStatus(model.status),
        model_metadata=_model_metadata_from_json(model.model_metadata)
        if model.model_metadata is not None
        else None,
        correlation_result=_correlation_result_from_json(model.correlation_result)
        if model.correlation_result is not None
        else None,
        regression_result=_regression_result_from_json(model.regression_result)
        if model.regression_result is not None
        else None,
        error=model.error,
        issued_by=model.issued_by,
        created_at=model.created_at,
    )


def apply_prediction_run_to_model(entity: PredictionRun, model: PredictionRunModel) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.assessment_id = uuid_module.UUID(entity.assessment_id)
    model.variable_selection_id = uuid_module.UUID(entity.variable_selection_id)
    model.sampling_campaign_id = uuid_module.UUID(entity.sampling_campaign_id)
    model.method = entity.method.value
    model.version = entity.version
    model.status = entity.status.value
    model.model_metadata = (
        _model_metadata_to_json(entity.model_metadata)
        if entity.model_metadata is not None
        else None
    )
    model.correlation_result = (
        _correlation_result_to_json(entity.correlation_result)
        if entity.correlation_result is not None
        else None
    )
    model.regression_result = (
        _regression_result_to_json(entity.regression_result)
        if entity.regression_result is not None
        else None
    )
    model.error = entity.error
    model.issued_by = entity.issued_by
    model.created_at = entity.created_at
