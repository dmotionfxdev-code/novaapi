"""Handler-level integration tests against a real Postgres instance —
``RunValidationHandler``'s resolve -> compute -> persist -> emit-events
pipeline, including the resolver-failure path that produces a
``ValidationRunErrored`` event instead of raising.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.validation.application.commands import RunValidationCommand
from georisk.contexts.validation.application.handlers import RunValidationHandler
from georisk.contexts.validation.application.ports import StubValidationSubjectResolver
from georisk.contexts.validation.domain.value_objects import (
    SubjectType,
    ValidationDataset,
    ValidationRunStatus,
)
from georisk.db.outbox_models import OutboxEventModel

pytestmark = pytest.mark.integration


class _AlwaysErrorsResolver:
    async def resolve(self, *, subject_id, subject_type, assessment_id):  # noqa: ANN001, ARG002
        raise RuntimeError("ground truth source unavailable")


class _FixedDatasetResolver:
    def __init__(self, dataset: ValidationDataset) -> None:
        self._dataset = dataset

    async def resolve(self, *, subject_id, subject_type, assessment_id):  # noqa: ANN001, ARG002
        return self._dataset


async def test_run_validation_with_stub_resolver_persists_and_emits_events(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RunValidationHandler(db_session, StubValidationSubjectResolver())

    run = await handler.handle(
        RunValidationCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            subject_id="stub:risk-stage",
            subject_type=SubjectType.STAGE_RESULT.value,
            issued_by="analyst-1",
        )
    )

    assert run.status == ValidationRunStatus.COMPLETED
    assert run.metrics is not None

    result = await db_session.execute(
        select(OutboxEventModel)
        .where(
            OutboxEventModel.aggregate_type == "ValidationRun",
            OutboxEventModel.aggregate_id == str(run.id),
        )
        .order_by(OutboxEventModel.sequence_number)
    )
    events = result.scalars().all()
    event_types = [e.event_type for e in events]
    assert event_types[0] == "validation.ValidationRunStarted"
    assert event_types[1] in ("validation.ValidationCompleted", "validation.ValidationFailed")


async def test_run_validation_resolver_failure_produces_errored_run_not_an_exception(
    db_session,  # noqa: ANN001
) -> None:
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    handler = RunValidationHandler(db_session, _AlwaysErrorsResolver())

    run = await handler.handle(
        RunValidationCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            subject_id="stub:risk-stage",
            subject_type=SubjectType.STAGE_RESULT.value,
            issued_by="system:workflow-engine",
        )
    )

    assert run.status == ValidationRunStatus.FAILED
    assert run.metrics is None
    assert "ground truth source unavailable" in run.error

    result = await db_session.execute(
        select(OutboxEventModel).where(
            OutboxEventModel.aggregate_type == "ValidationRun",
            OutboxEventModel.aggregate_id == str(run.id),
        )
    )
    event_types = {e.event_type for e in result.scalars().all()}
    assert "validation.ValidationRunErrored" in event_types


async def test_run_validation_produces_fail_verdict_for_a_bad_dataset(db_session) -> None:  # noqa: ANN001
    tenant_id = TenantId.new()
    assessment_id = str(uuid.uuid4())
    bad_dataset = ValidationDataset(
        y_true=("POSITIVE", "POSITIVE", "NEGATIVE", "NEGATIVE"),
        y_pred=("NEGATIVE", "NEGATIVE", "POSITIVE", "POSITIVE"),
        labels=("NEGATIVE", "POSITIVE"),
    )
    handler = RunValidationHandler(db_session, _FixedDatasetResolver(bad_dataset))

    run = await handler.handle(
        RunValidationCommand(
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            subject_id="stub:risk-stage",
            subject_type=SubjectType.STAGE_RESULT.value,
            issued_by="analyst-1",
        )
    )

    assert run.status == ValidationRunStatus.COMPLETED
    assert run.verdict.value == "FAIL"
    assert run.metrics.overall_accuracy == 0.0
