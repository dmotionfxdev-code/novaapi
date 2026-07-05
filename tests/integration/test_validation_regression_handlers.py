"""Handler-level integration tests against a real Postgres instance —
``RunRegressionValidationHandler``'s resolve -> persist -> emit-events
pipeline, including the resolver-failure path that produces a
``ValidationRunErrored`` event instead of raising. Uses fake resolvers
(not the real composition-root one, which needs a genuine Prediction
stack — proven separately in ``test_validation_regression_api.py``'s
live-HTTP test).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.validation.application.commands import RunRegressionValidationCommand
from georisk.contexts.validation.application.handlers import RunRegressionValidationHandler
from georisk.contexts.validation.application.ports import (
    RegressionValidationSubject,
    StubRegressionValidationSubjectResolver,
)
from georisk.contexts.validation.domain.value_objects import (
    RegressionMetricSet,
    SubjectType,
    ValidationMode,
    ValidationRunStatus,
)
from georisk.db.outbox_models import OutboxEventModel

pytestmark = pytest.mark.integration


class _AlwaysErrorsResolver:
    async def resolve(self, *, subject_id, assessment_id, tenant_id):  # noqa: ANN001, ARG002
        raise ValueError("PredictionRun not found")


class _FixedSubjectResolver:
    def __init__(self, subject: RegressionValidationSubject) -> None:
        self._subject = subject

    async def resolve(self, *, subject_id, assessment_id, tenant_id):  # noqa: ANN001, ARG002
        return self._subject


async def test_run_regression_validation_with_stub_resolver_persists_and_emits_events(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RunRegressionValidationHandler(db_session, StubRegressionValidationSubjectResolver())

    run = await handler.handle(
        RunRegressionValidationCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            subject_id=str(uuid.uuid4()),
            issued_by="analyst-1",
        )
    )

    assert run.status == ValidationRunStatus.COMPLETED
    assert run.mode == ValidationMode.REGRESSION
    assert run.subject_type is SubjectType.PREDICTION
    assert run.regression_metrics is not None

    result = await db_session.execute(
        select(OutboxEventModel)
        .where(
            OutboxEventModel.aggregate_type == "ValidationRun",
            OutboxEventModel.aggregate_id == str(run.id),
        )
        .order_by(OutboxEventModel.sequence_number)
    )
    event_types = [e.event_type for e in result.scalars().all()]
    assert event_types[0] == "validation.ValidationRunStarted"
    assert event_types[1] in (
        "validation.RegressionValidationCompleted",
        "validation.RegressionValidationFailed",
    )


async def test_run_regression_validation_resolver_failure_produces_errored_run(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RunRegressionValidationHandler(db_session, _AlwaysErrorsResolver())

    run = await handler.handle(
        RunRegressionValidationCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            subject_id=str(uuid.uuid4()),
            issued_by="analyst-1",
        )
    )

    assert run.status == ValidationRunStatus.FAILED
    assert run.mode == ValidationMode.REGRESSION
    assert run.regression_metrics is None
    assert "PredictionRun not found" in run.error

    result = await db_session.execute(
        select(OutboxEventModel).where(
            OutboxEventModel.aggregate_type == "ValidationRun",
            OutboxEventModel.aggregate_id == str(run.id),
        )
    )
    event_types = {e.event_type for e in result.scalars().all()}
    assert "validation.ValidationRunErrored" in event_types


async def test_run_regression_validation_produces_fail_verdict_for_a_poor_fit(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    poor_metrics = RegressionMetricSet(
        sample_size=10, rmse=50.0, mae=45.0, mse=2500.0, r_squared=0.1, adjusted_r_squared=0.0
    )
    subject = RegressionValidationSubject(metrics=poor_metrics, model_metadata=None)
    handler = RunRegressionValidationHandler(db_session, _FixedSubjectResolver(subject))

    run = await handler.handle(
        RunRegressionValidationCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            subject_id=str(uuid.uuid4()),
            issued_by="analyst-1",
        )
    )

    assert run.status == ValidationRunStatus.COMPLETED
    assert run.verdict.value == "FAIL"
    assert run.regression_metrics.r_squared == pytest.approx(0.1)
