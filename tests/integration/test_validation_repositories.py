"""Repository-level integration tests against a real Postgres instance —
confirms the ``ValidationRun`` domain<->ORM mapping round-trips correctly
(including the JSONB metrics/thresholds shape), and that cursor pagination
scoped to one assessment works.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.validation.domain.entities import ValidationRun
from georisk.contexts.validation.domain.metrics import compute_metric_set
from georisk.contexts.validation.domain.regression_metrics import compute_regression_metric_set
from georisk.contexts.validation.domain.value_objects import (
    RegressionModelMetadata,
    RegressionValidationDataset,
    SubjectType,
    ValidationDataset,
    ValidationMode,
    ValidationRunStatus,
    ValidationThresholds,
)
from georisk.contexts.validation.infrastructure.repositories import (
    SqlAlchemyValidationRunRepository,
)

pytestmark = pytest.mark.integration


def _metrics_with_roc():
    dataset = ValidationDataset(
        y_true=("NEGATIVE", "NEGATIVE", "POSITIVE", "POSITIVE"),
        y_pred=("NEGATIVE", "NEGATIVE", "POSITIVE", "POSITIVE"),
        y_scores=(0.1, 0.4, 0.35, 0.8),
        labels=("NEGATIVE", "POSITIVE"),
    )
    return compute_metric_set(dataset)


async def test_save_and_get_round_trips(db_session) -> None:  # noqa: ANN001
    assessment_id = str(uuid.uuid4())
    run, _started, _outcome = ValidationRun.complete(
        tenant_id=TenantId.new(),
        assessment_id=assessment_id,
        subject_id="stub:subject-1",
        subject_type=SubjectType.STAGE_RESULT,
        thresholds=ValidationThresholds(min_overall_accuracy=0.7, min_auc=0.6),
        metrics=_metrics_with_roc(),
        issued_by="analyst-1",
    )
    repo = SqlAlchemyValidationRunRepository(db_session)
    await repo.save(run)
    await db_session.flush()

    fetched = await repo.get_by_id(run.id)
    assert fetched is not None
    assert fetched.assessment_id == assessment_id
    assert fetched.subject_id == "stub:subject-1"
    assert fetched.subject_type == SubjectType.STAGE_RESULT
    assert fetched.status == ValidationRunStatus.COMPLETED
    assert fetched.verdict == run.verdict
    assert fetched.metrics is not None
    assert fetched.metrics.auc == pytest.approx(0.75)
    assert fetched.metrics.confusion_matrix.labels == ("NEGATIVE", "POSITIVE")
    assert fetched.thresholds.min_overall_accuracy == 0.7
    assert fetched.thresholds.min_auc == 0.6


async def test_errored_run_round_trips_with_no_metrics(db_session) -> None:  # noqa: ANN001
    assessment_id = str(uuid.uuid4())
    run, _started, _errored = ValidationRun.errored(
        tenant_id=TenantId.new(),
        assessment_id=assessment_id,
        subject_id="stub:subject-2",
        subject_type=SubjectType.PREDICTION,
        thresholds=ValidationThresholds(),
        error="boom",
        issued_by="system:workflow-engine",
    )
    repo = SqlAlchemyValidationRunRepository(db_session)
    await repo.save(run)
    await db_session.flush()

    fetched = await repo.get_by_id(run.id)
    assert fetched is not None
    assert fetched.status == ValidationRunStatus.FAILED
    assert fetched.metrics is None
    assert fetched.verdict is None
    assert fetched.error == "boom"


async def test_list_by_assessment_scoped_and_paginated(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_a = str(uuid.uuid4())
    assessment_b = str(uuid.uuid4())
    repo = SqlAlchemyValidationRunRepository(db_session)

    for i in range(3):
        run, _s, _o = ValidationRun.complete(
            tenant_id=tenant_id,
            assessment_id=assessment_a,
            subject_id=f"stub:subject-a-{i}",
            subject_type=SubjectType.STAGE_RESULT,
            thresholds=ValidationThresholds(),
            metrics=_metrics_with_roc(),
            issued_by="analyst-1",
        )
        await repo.save(run)
    other_run, _s, _o = ValidationRun.complete(
        tenant_id=tenant_id,
        assessment_id=assessment_b,
        subject_id="stub:subject-b",
        subject_type=SubjectType.STAGE_RESULT,
        thresholds=ValidationThresholds(),
        metrics=_metrics_with_roc(),
        issued_by="analyst-1",
    )
    await repo.save(other_run)
    await db_session.flush()

    page1, cursor1, has_more1 = await repo.list_by_assessment(
        tenant_id, assessment_a, limit=2, cursor=None
    )
    assert len(page1) == 2
    assert has_more1 is True

    page2, _cursor2, has_more2 = await repo.list_by_assessment(
        tenant_id, assessment_a, limit=2, cursor=cursor1
    )
    assert len(page2) == 1
    assert has_more2 is False
    assert {r.assessment_id for r in page1 + page2} == {assessment_a}


async def test_list_by_assessment_is_tenant_scoped(db_session) -> None:  # noqa: ANN001
    tenant_a = TenantId.new()
    tenant_b = TenantId.new()
    assessment_id = str(uuid.uuid4())
    repo = SqlAlchemyValidationRunRepository(db_session)

    run_a, _s, _o = ValidationRun.complete(
        tenant_id=tenant_a,
        assessment_id=assessment_id,
        subject_id="stub:a",
        subject_type=SubjectType.STAGE_RESULT,
        thresholds=ValidationThresholds(),
        metrics=_metrics_with_roc(),
        issued_by="analyst-1",
    )
    await repo.save(run_a)
    await db_session.flush()

    results, _cursor, _has_more = await repo.list_by_assessment(
        tenant_b, assessment_id, limit=10, cursor=None
    )
    assert results == []


async def test_regression_run_round_trips_with_model_metadata(db_session) -> None:  # noqa: ANN001
    assessment_id = str(uuid.uuid4())
    dataset = RegressionValidationDataset(
        y_true=(10.0, 20.0, 15.0, 25.0, 30.0, 12.0, 18.0, 22.0, 28.0, 16.0),
        y_pred=(12.5, 17.5, 17.0, 22.0, 27.5, 14.5, 15.5, 24.5, 25.0, 18.5),
        num_predictors=2,
    )
    metrics = compute_regression_metric_set(dataset)
    model_metadata = RegressionModelMetadata(
        prediction_run_id=str(uuid.uuid4()),
        method="MULTIPLE_LINEAR_REGRESSION",
        formula_version="mlr-ols-v1",
        predictor_variable_codes=("ndvi", "wind_speed"),
        dependent_variable_code="burned_area",
        sample_size=1000,
        computed_at=datetime.now(UTC),
    )
    run, _started, _outcome = ValidationRun.complete_regression(
        tenant_id=TenantId.new(),
        assessment_id=assessment_id,
        subject_id=model_metadata.prediction_run_id,
        thresholds=ValidationThresholds(min_r_squared=0.5, max_rmse=5.0),
        metrics=metrics,
        model_metadata=model_metadata,
        issued_by="analyst-1",
    )
    repo = SqlAlchemyValidationRunRepository(db_session)
    await repo.save(run)
    await db_session.flush()

    fetched = await repo.get_by_id(run.id)
    assert fetched is not None
    assert fetched.mode == ValidationMode.REGRESSION
    assert fetched.subject_type == SubjectType.PREDICTION
    assert fetched.metrics is None
    assert fetched.regression_metrics is not None
    assert fetched.regression_metrics.rmse == pytest.approx(2.564176, abs=1e-5)
    assert fetched.model_metadata is not None
    assert fetched.model_metadata.formula_version == "mlr-ols-v1"
    assert fetched.model_metadata.predictor_variable_codes == ("ndvi", "wind_speed")
    assert fetched.thresholds.min_r_squared == 0.5
