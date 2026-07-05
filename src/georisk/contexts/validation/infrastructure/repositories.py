"""Concrete SQLAlchemy repository implementing
``contexts/validation/domain/repositories.ValidationRunRepository``.

No optimistic-concurrency version check on ``save`` — a ``ValidationRun``
is write-once (`entities.py`'s module docstring: both construction paths
produce a fully-formed, terminal entity in one call, there is no further
transition that could race). ``version`` is still persisted for schema
consistency with every other aggregate in this codebase, just never
compared against on write.
"""

from __future__ import annotations

import base64
import json
import uuid as uuid_module
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.validation.domain.entities import ValidationRun
from georisk.contexts.validation.domain.value_objects import ValidationRunId
from georisk.contexts.validation.infrastructure import mappers
from georisk.contexts.validation.infrastructure.models import ValidationRunModel


class SqlAlchemyValidationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, validation_run_id: ValidationRunId) -> ValidationRun | None:
        model = await self._session.get(ValidationRunModel, validation_run_id.value)
        return mappers.validation_run_to_domain(model) if model else None

    async def list_by_assessment(
        self,
        tenant_id: TenantId,
        assessment_id: str,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[ValidationRun], str | None, bool]:
        """Cursor pagination keyed on ``(created_at, id)`` — same convention
        as `AssessmentRepository.list_by_tenant` (Sprint 2).
        """
        query = select(ValidationRunModel).where(
            ValidationRunModel.tenant_id == tenant_id.value,
            ValidationRunModel.assessment_id == uuid_module.UUID(assessment_id),
        )
        query = query.order_by(ValidationRunModel.created_at, ValidationRunModel.id)

        if cursor:
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            cursor_created_at = datetime.fromisoformat(decoded["created_at"])
            cursor_id = uuid_module.UUID(decoded["id"])
            query = query.where(
                (ValidationRunModel.created_at > cursor_created_at)
                | (
                    (ValidationRunModel.created_at == cursor_created_at)
                    & (ValidationRunModel.id > cursor_id)
                )
            )
        query = query.limit(limit + 1)

        result = await self._session.execute(query)
        models = list(result.scalars().all())
        has_more = len(models) > limit
        models = models[:limit]
        runs = [mappers.validation_run_to_domain(m) for m in models]

        next_cursor = None
        if has_more and models:
            last = models[-1]
            payload = json.dumps({"created_at": last.created_at.isoformat(), "id": str(last.id)})
            next_cursor = base64.urlsafe_b64encode(payload.encode()).decode()

        return runs, next_cursor, has_more

    async def save(self, validation_run: ValidationRun) -> None:
        model = ValidationRunModel(version=0)
        mappers.apply_validation_run_to_model(validation_run, model)
        self._session.add(model)
