"""Repository-level integration tests against a real Postgres instance —
confirms ``PredictionRun``'s domain<->ORM mapping round-trips correctly,
including both correlation and regression result shapes, and that
``next_version`` increments per ``(assessment, variable_selection,
method)``.
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
    RegressionResult,
    RegressionVariableResult,
)
from georisk.contexts.prediction.infrastructure.repositories import (
    SqlAlchemyPredictionRunRepository,
)

pytestmark = pytest.mark.integration


def _model_metadata(method: PredictionMethod, dependent: str | None = None) -> ModelMetadata:
    return ModelMetadata(
        model_type=method,
        formula_version="test-v1",
        predictor_variable_codes=("ndvi", "wind_speed"),
        dependent_variable_code=dependent,
        sample_size=1000,
        computed_at=datetime.now(UTC),
    )


async def test_correlation_run_save_and_get_round_trips(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    variable_selection_id = str(uuid.uuid4())
    sampling_campaign_id = str(uuid.uuid4())

    correlation_result = CorrelationResult(
        pairs=(
            CorrelationPair(
                variable_a="ndvi", variable_b="wind_speed", coefficient=0.42, sample_size=1000
            ),
        )
    )
    run, _event = PredictionRun.complete_correlation(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        variable_selection_id=variable_selection_id,
        sampling_campaign_id=sampling_campaign_id,
        method=PredictionMethod.PEARSON_CORRELATION,
        version=1,
        result=correlation_result,
        model_metadata=_model_metadata(PredictionMethod.PEARSON_CORRELATION),
        issued_by="analyst-1",
    )
    repo = SqlAlchemyPredictionRunRepository(db_session)
    await repo.save(run)
    await db_session.flush()

    fetched = await repo.get_by_id(run.id)
    assert fetched is not None
    assert fetched.correlation_result is not None
    assert fetched.correlation_result.get("ndvi", "wind_speed") == pytest.approx(0.42)
    assert fetched.model_metadata is not None
    assert fetched.model_metadata.formula_version == "test-v1"


async def test_regression_run_save_and_get_round_trips(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    variable_selection_id = str(uuid.uuid4())
    sampling_campaign_id = str(uuid.uuid4())

    regression_result = RegressionResult(
        intercept=5.0,
        variables=(
            RegressionVariableResult(
                code="ndvi",
                coefficient=2.0,
                standardized_coefficient=0.6,
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
    run, _event = PredictionRun.complete_regression(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        variable_selection_id=variable_selection_id,
        sampling_campaign_id=sampling_campaign_id,
        version=1,
        result=regression_result,
        model_metadata=_model_metadata(
            PredictionMethod.MULTIPLE_LINEAR_REGRESSION, dependent="burned_area"
        ),
        issued_by="analyst-1",
    )
    repo = SqlAlchemyPredictionRunRepository(db_session)
    await repo.save(run)
    await db_session.flush()

    fetched = await repo.get_by_id(run.id)
    assert fetched is not None
    assert fetched.regression_result is not None
    assert fetched.regression_result.intercept == pytest.approx(5.0)
    assert fetched.regression_result.coefficient("ndvi") == pytest.approx(2.0)
    assert fetched.regression_result.r_squared == pytest.approx(0.95)


async def test_next_version_increments_per_selection_and_method(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    variable_selection_id = str(uuid.uuid4())
    sampling_campaign_id = str(uuid.uuid4())
    repo = SqlAlchemyPredictionRunRepository(db_session)

    assert (
        await repo.next_version(
            tenant_id, assessment_id, variable_selection_id, PredictionMethod.PEARSON_CORRELATION
        )
        == 1
    )

    run, _event = PredictionRun.complete_correlation(
        tenant_id=tenant_id,
        assessment_id=assessment_id,
        variable_selection_id=variable_selection_id,
        sampling_campaign_id=sampling_campaign_id,
        method=PredictionMethod.PEARSON_CORRELATION,
        version=1,
        result=CorrelationResult(pairs=()),
        model_metadata=_model_metadata(PredictionMethod.PEARSON_CORRELATION),
        issued_by="analyst-1",
    )
    await repo.save(run)
    await db_session.flush()

    assert (
        await repo.next_version(
            tenant_id, assessment_id, variable_selection_id, PredictionMethod.PEARSON_CORRELATION
        )
        == 2
    )
    # A different method on the same selection starts its own count.
    assert (
        await repo.next_version(
            tenant_id,
            assessment_id,
            variable_selection_id,
            PredictionMethod.MULTIPLE_LINEAR_REGRESSION,
        )
        == 1
    )


async def test_list_by_assessment_returns_all_runs(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    variable_selection_id = str(uuid.uuid4())
    sampling_campaign_id = str(uuid.uuid4())
    repo = SqlAlchemyPredictionRunRepository(db_session)

    for method in (PredictionMethod.PEARSON_CORRELATION, PredictionMethod.SPEARMAN_CORRELATION):
        run, _event = PredictionRun.complete_correlation(
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            variable_selection_id=variable_selection_id,
            sampling_campaign_id=sampling_campaign_id,
            method=method,
            version=1,
            result=CorrelationResult(pairs=()),
            model_metadata=_model_metadata(method),
            issued_by="analyst-1",
        )
        await repo.save(run)
    await db_session.flush()

    runs = await repo.list_by_assessment(tenant_id, assessment_id)
    assert len(runs) == 2
