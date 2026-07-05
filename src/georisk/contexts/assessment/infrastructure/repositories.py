"""Concrete SQLAlchemy repository implementing
``contexts/assessment/domain/repositories.AssessmentRepository``.
"""

from __future__ import annotations

import base64
import json
import uuid as uuid_module
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.errors import OptimisticConcurrencyError
from georisk.contexts.assessment.domain.value_objects import (
    AssessmentId,
    AssessmentStatus,
    HazardType,
)
from georisk.contexts.assessment.infrastructure import mappers
from georisk.contexts.assessment.infrastructure.models import AssessmentModel
from georisk.contexts.identity.domain.value_objects import TenantId


class SqlAlchemyAssessmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, assessment_id: AssessmentId) -> Assessment | None:
        model = await self._session.get(AssessmentModel, assessment_id.value)
        return mappers.assessment_to_domain(model) if model else None

    async def list_by_tenant(
        self,
        tenant_id: TenantId,
        *,
        limit: int,
        cursor: str | None,
        status: AssessmentStatus | None = None,
        hazard_type: HazardType | None = None,
    ) -> tuple[list[Assessment], str | None, bool]:
        """Cursor pagination keyed on ``(created_at, id)`` (API Resource
        Model §6), identical convention to Identity's ``UserRepository``
        (Sprint 1) — deliberately duplicated rather than shared, since a
        premature "generic paginated repository" abstraction across two
        data shapes isn't worth the coupling it would introduce this early
        (coding standard: no abstraction beyond what's needed).
        """
        query = select(AssessmentModel).where(AssessmentModel.tenant_id == tenant_id.value)
        if status is not None:
            query = query.where(AssessmentModel.status == status.value)
        if hazard_type is not None:
            query = query.where(AssessmentModel.hazard_type == hazard_type.value)
        query = query.order_by(AssessmentModel.created_at, AssessmentModel.id)

        if cursor:
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            cursor_created_at = datetime.fromisoformat(decoded["created_at"])
            cursor_id = uuid_module.UUID(decoded["id"])
            query = query.where(
                (AssessmentModel.created_at > cursor_created_at)
                | (
                    (AssessmentModel.created_at == cursor_created_at)
                    & (AssessmentModel.id > cursor_id)
                )
            )
        query = query.limit(limit + 1)

        result = await self._session.execute(query)
        models = list(result.scalars().all())
        has_more = len(models) > limit
        models = models[:limit]
        assessments = [mappers.assessment_to_domain(m) for m in models]

        next_cursor = None
        if has_more and models:
            last = models[-1]
            payload = json.dumps({"created_at": last.created_at.isoformat(), "id": str(last.id)})
            next_cursor = base64.urlsafe_b64encode(payload.encode()).decode()

        return assessments, next_cursor, has_more

    async def save(self, assessment: Assessment, *, expected_version: int | None = None) -> None:
        model = await self._session.get(AssessmentModel, assessment.id.value)
        if model is None:
            model = AssessmentModel(version=0)
            mappers.apply_assessment_to_model(assessment, model)
            self._session.add(model)
            return

        if expected_version is not None and model.version != expected_version:
            raise OptimisticConcurrencyError(
                f"Assessment {assessment.id} was modified concurrently "
                f"(expected version {expected_version}, found {model.version})"
            )
        mappers.apply_assessment_to_model(assessment, model)
        model.version = model.version + 1
