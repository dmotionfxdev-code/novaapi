"""Repository interface — domain layer contract (Application Layer §1: one
repository per aggregate root, coarse-grained ``get``/``save`` only).
Concrete SQLAlchemy implementation lives in
``contexts/validation/infrastructure/repositories.py``.
"""

from __future__ import annotations

from typing import Protocol

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.validation.domain.entities import ValidationRun
from georisk.contexts.validation.domain.value_objects import ValidationRunId


class ValidationRunRepository(Protocol):
    async def get_by_id(self, validation_run_id: ValidationRunId) -> ValidationRun | None: ...

    async def list_by_assessment(
        self,
        tenant_id: TenantId,
        assessment_id: str,
        *,
        limit: int,
        cursor: str | None,
    ) -> tuple[list[ValidationRun], str | None, bool]: ...

    async def save(self, validation_run: ValidationRun) -> None: ...
