"""``RunValidationCommand`` handler — one transaction, one aggregate
(``ValidationRun``), per Application Layer §9. Resolves the subject's
dataset, computes its metrics, constructs a fully-formed ``ValidationRun``
(``complete()`` on success, ``error()`` if resolution/computation raises),
saves, appends both resulting events to the outbox, commits. Never touches
anything in ``contexts.assessment`` — the "Validation never mutates
Assessment directly" requirement, structurally true here since this module
has no import path to that context at all (import-linter's peer-
independence contract would fail the build if it did).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.validation.application.commands import (
    RunRegressionValidationCommand,
    RunValidationCommand,
)
from georisk.contexts.validation.application.ports import (
    RegressionValidationSubjectResolver,
    ValidationSubjectResolver,
)
from georisk.contexts.validation.domain.entities import ValidationRun
from georisk.contexts.validation.domain.events import (
    RegressionValidationCompleted,
    RegressionValidationFailed,
    ValidationCompleted,
    ValidationFailed,
    ValidationRunErrored,
)
from georisk.contexts.validation.domain.metrics import (
    DEFAULT_VALIDATION_THRESHOLDS,
    compute_metric_set,
)
from georisk.contexts.validation.domain.regression_metrics import (
    DEFAULT_REGRESSION_VALIDATION_THRESHOLDS,
)
from georisk.contexts.validation.domain.value_objects import SubjectType, ValidationMode
from georisk.contexts.validation.infrastructure.repositories import (
    SqlAlchemyValidationRunRepository,
)
from georisk.db.outbox_writer import append_event


class RunValidationHandler:
    def __init__(self, session: AsyncSession, resolver: ValidationSubjectResolver) -> None:
        self._session = session
        self._resolver = resolver

    async def handle(self, command: RunValidationCommand) -> ValidationRun:
        tenant_id = TenantId.from_string(command.tenant_id)
        subject_type = SubjectType(command.subject_type)
        repo = SqlAlchemyValidationRunRepository(self._session)

        outcome_event: ValidationCompleted | ValidationFailed | ValidationRunErrored
        try:
            dataset = await self._resolver.resolve(
                subject_id=command.subject_id,
                subject_type=subject_type,
                assessment_id=command.assessment_id,
            )
            metrics = compute_metric_set(dataset)
            run, started_event, outcome_event = ValidationRun.complete(
                tenant_id=tenant_id,
                assessment_id=command.assessment_id,
                subject_id=command.subject_id,
                subject_type=subject_type,
                thresholds=DEFAULT_VALIDATION_THRESHOLDS,
                metrics=metrics,
                issued_by=command.issued_by,
            )
        except Exception as exc:  # noqa: BLE001 — quarantining a pluggable
            # resolver's failure into a domain fact (ValidationRun.FAILED +
            # ValidationRunErrored), not letting it crash the request; the
            # same "isolate an untrusted boundary" reasoning as
            # WorkflowEngine's stage-retry path, applied to resolution
            # instead of execution.
            run, started_event, outcome_event = ValidationRun.errored(
                tenant_id=tenant_id,
                assessment_id=command.assessment_id,
                subject_id=command.subject_id,
                subject_type=subject_type,
                thresholds=DEFAULT_VALIDATION_THRESHOLDS,
                error=str(exc),
                issued_by=command.issued_by,
            )

        await repo.save(run)
        for event in (started_event, outcome_event):
            await append_event(
                self._session,
                aggregate_type="ValidationRun",
                aggregate_id=str(run.id),
                event_type=event.event_type,
                payload=event.payload(),
                tenant_id=tenant_id.value,
            )
        await self._session.commit()
        return run


class RunRegressionValidationHandler:
    """Sprint 10's regression-mode counterpart of ``RunValidationHandler``.
    ``subject_type`` is always ``PREDICTION`` — fixed inside
    ``ValidationRun.complete_regression()``, never a parameter here either.
    """

    def __init__(
        self, session: AsyncSession, resolver: RegressionValidationSubjectResolver
    ) -> None:
        self._session = session
        self._resolver = resolver

    async def handle(self, command: RunRegressionValidationCommand) -> ValidationRun:
        tenant_id = TenantId.from_string(command.tenant_id)
        repo = SqlAlchemyValidationRunRepository(self._session)

        outcome_event: (
            RegressionValidationCompleted | RegressionValidationFailed | ValidationRunErrored
        )
        try:
            subject = await self._resolver.resolve(
                subject_id=command.subject_id,
                assessment_id=command.assessment_id,
                tenant_id=command.tenant_id,
            )
            run, started_event, outcome_event = ValidationRun.complete_regression(
                tenant_id=tenant_id,
                assessment_id=command.assessment_id,
                subject_id=command.subject_id,
                thresholds=DEFAULT_REGRESSION_VALIDATION_THRESHOLDS,
                metrics=subject.metrics,
                model_metadata=subject.model_metadata,
                issued_by=command.issued_by,
            )
        except Exception as exc:  # noqa: BLE001 — quarantining a pluggable
            # resolver's failure (subject not found, not a regression
            # PredictionRun) into a domain fact (ValidationRun.FAILED +
            # ValidationRunErrored), the same "isolate an untrusted
            # boundary" reasoning as ``RunValidationHandler``.
            run, started_event, outcome_event = ValidationRun.errored(
                tenant_id=tenant_id,
                assessment_id=command.assessment_id,
                subject_id=command.subject_id,
                subject_type=SubjectType.PREDICTION,
                thresholds=DEFAULT_REGRESSION_VALIDATION_THRESHOLDS,
                error=str(exc),
                issued_by=command.issued_by,
                mode=ValidationMode.REGRESSION,
            )

        await repo.save(run)
        for event in (started_event, outcome_event):
            await append_event(
                self._session,
                aggregate_type="ValidationRun",
                aggregate_id=str(run.id),
                event_type=event.event_type,
                payload=event.payload(),
                tenant_id=tenant_id.value,
            )
        await self._session.commit()
        return run
