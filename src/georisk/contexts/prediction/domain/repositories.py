"""Repository interface — domain layer contract (Application Layer §1:
one repository per aggregate root). Concrete SQLAlchemy implementation
lives in ``contexts/prediction/infrastructure/repositories.py``.
"""

from __future__ import annotations

from typing import Protocol

from georisk.contexts.identity.domain.value_objects import TenantId
from georisk.contexts.prediction.domain.entities import PredictionRun
from georisk.contexts.prediction.domain.value_objects import PredictionMethod, PredictionRunId


class PredictionRunRepository(Protocol):
    async def get_by_id(self, prediction_run_id: PredictionRunId) -> PredictionRun | None: ...

    async def list_by_assessment(
        self, tenant_id: TenantId, assessment_id: str
    ) -> list[PredictionRun]: ...

    async def next_version(
        self,
        tenant_id: TenantId,
        assessment_id: str,
        variable_selection_id: str,
        method: PredictionMethod,
    ) -> int: ...

    async def save(self, run: PredictionRun) -> None: ...
