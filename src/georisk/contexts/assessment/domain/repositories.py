"""Repository interface — domain layer contract (Application Layer §1: one
repository per aggregate root, coarse-grained ``get``/``save`` only).
Concrete SQLAlchemy implementation lives in
``contexts/assessment/infrastructure/repositories.py``.
"""

from __future__ import annotations

from typing import Protocol

from georisk.contexts.assessment.domain.entities import Assessment
from georisk.contexts.assessment.domain.value_objects import (
    AssessmentId,
    AssessmentStatus,
    HazardType,
)
from georisk.contexts.identity.domain.value_objects import TenantId


class AssessmentRepository(Protocol):
    async def get_by_id(self, assessment_id: AssessmentId) -> Assessment | None: ...

    async def list_by_tenant(
        self,
        tenant_id: TenantId,
        *,
        limit: int,
        cursor: str | None,
        status: AssessmentStatus | None = None,
        hazard_type: HazardType | None = None,
    ) -> tuple[list[Assessment], str | None, bool]: ...

    async def save(
        self, assessment: Assessment, *, expected_version: int | None = None
    ) -> None: ...
