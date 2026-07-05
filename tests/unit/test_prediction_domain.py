"""Domain-layer unit tests for the ``PredictionRun`` aggregate — pure
logic, no I/O.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.prediction.domain.entities import PredictionRun
from georisk.contexts.prediction.domain.value_objects import (
    CorrelationPair,
    CorrelationResult,
    ModelMetadata,
    PredictionMethod,
    PredictionRunStatus,
    RegressionResult,
    RegressionVariableResult,
)

pytestmark = pytest.mark.unit


def _model_metadata(method: PredictionMethod, dependent: str | None = None) -> ModelMetadata:
    return ModelMetadata(
        model_type=method,
        formula_version="test-v1",
        predictor_variable_codes=("ndvi", "wind_speed"),
        dependent_variable_code=dependent,
        sample_size=1000,
        computed_at=datetime.now(UTC),
    )


def test_complete_correlation_produces_completed_event() -> None:
    result = CorrelationResult(
        pairs=(
            CorrelationPair(
                variable_a="ndvi", variable_b="wind_speed", coefficient=0.42, sample_size=1000
            ),
        )
    )
    run, event = PredictionRun.complete_correlation(
        tenant_id=TenantId.new(),
        assessment_id=str(uuid.uuid4()),
        variable_selection_id=str(uuid.uuid4()),
        sampling_campaign_id=str(uuid.uuid4()),
        method=PredictionMethod.PEARSON_CORRELATION,
        version=1,
        result=result,
        model_metadata=_model_metadata(PredictionMethod.PEARSON_CORRELATION),
        issued_by="analyst-1",
    )
    assert run.status == PredictionRunStatus.COMPLETED
    assert run.correlation_result is result
    assert run.regression_result is None
    assert event.event_type == "prediction.PredictionRunCompleted"
    assert event.method == "PEARSON_CORRELATION"
    assert event.sample_size == 1000


def test_complete_regression_produces_completed_event() -> None:
    result = RegressionResult(
        intercept=5.0,
        variables=(
            RegressionVariableResult(
                code="ndvi",
                coefficient=2.0,
                standardized_coefficient=0.5,
                standard_error=0.1,
                t_statistic=20.0,
                p_value=0.0001,
            ),
        ),
        r_squared=0.95,
        adjusted_r_squared=0.94,
        rmse=0.1,
        mae=0.08,
        f_statistic=100.0,
        mse=0.01,
    )
    run, event = PredictionRun.complete_regression(
        tenant_id=TenantId.new(),
        assessment_id=str(uuid.uuid4()),
        variable_selection_id=str(uuid.uuid4()),
        sampling_campaign_id=str(uuid.uuid4()),
        version=1,
        result=result,
        model_metadata=_model_metadata(
            PredictionMethod.MULTIPLE_LINEAR_REGRESSION, dependent="burned_area"
        ),
        issued_by="analyst-1",
    )
    assert run.status == PredictionRunStatus.COMPLETED
    assert run.method == PredictionMethod.MULTIPLE_LINEAR_REGRESSION
    assert run.regression_result is result
    assert run.correlation_result is None
    assert event.formula_version == "test-v1"


def test_failed_produces_failed_event_with_no_results() -> None:
    run, event = PredictionRun.failed(
        tenant_id=TenantId.new(),
        assessment_id=str(uuid.uuid4()),
        variable_selection_id=str(uuid.uuid4()),
        sampling_campaign_id=str(uuid.uuid4()),
        method=PredictionMethod.MULTIPLE_LINEAR_REGRESSION,
        version=1,
        error="VariableSelection is not CONFIRMED",
        issued_by="analyst-1",
    )
    assert run.status == PredictionRunStatus.FAILED
    assert run.model_metadata is None
    assert run.correlation_result is None
    assert run.regression_result is None
    assert event.event_type == "prediction.PredictionRunFailed"
    assert event.error == "VariableSelection is not CONFIRMED"


def test_correlation_result_get_is_symmetric() -> None:
    result = CorrelationResult(
        pairs=(CorrelationPair(variable_a="a", variable_b="b", coefficient=0.7, sample_size=10),)
    )
    assert result.get("a", "b") == 0.7
    assert result.get("b", "a") == 0.7
    assert result.get("a", "c") is None


def test_regression_result_coefficient_lookup() -> None:
    result = RegressionResult(
        intercept=1.0,
        variables=(
            RegressionVariableResult(
                code="ndvi",
                coefficient=2.5,
                standardized_coefficient=0.4,
                standard_error=0.2,
                t_statistic=12.5,
                p_value=0.001,
            ),
        ),
        r_squared=0.8,
        adjusted_r_squared=0.78,
        rmse=0.2,
        mae=0.15,
        f_statistic=50.0,
        mse=0.04,
    )
    assert result.coefficient("ndvi") == 2.5
    assert result.coefficient("missing") is None
