"""Repository interface — domain layer contract (Application Layer §1: one
repository per aggregate root). Infrastructure Architecture §2 calls this
out specifically: "``StageResultRepository`` is a single generic
implementation parameterized by ``(hazardType, stageType)``... the one
repository that most directly embodies 'one platform, four hazard types.'"
Concrete SQLAlchemy implementation lives in
``contexts/analysis/infrastructure/repositories.py``.
"""

from __future__ import annotations

from typing import Protocol

from georisk.contexts.analysis.domain.entities import RiskLayer, StageResult
from georisk.contexts.analysis.domain.value_objects import (
    HazardType,
    RiskLayerId,
    StageResultId,
    StageType,
)
from georisk.contexts.identity.domain.value_objects import TenantId


class StageResultRepository(Protocol):
    async def get_by_id(self, stage_result_id: StageResultId) -> StageResult | None: ...

    async def get_latest(
        self, tenant_id: TenantId, assessment_id: str, stage_type: StageType
    ) -> StageResult | None:
        """The most recent (highest ``version``) result for one
        assessment's one stage — what a downstream calculator (Risk
        reading Vulnerability, Resilience reading Vulnerability) queries,
        never a live join across aggregates (Application Layer §12's
        worked trace: "reads ... results via query, not live join —
        respects aggregate boundaries").
        """
        ...

    async def list_by_assessment(
        self, tenant_id: TenantId, assessment_id: str
    ) -> list[StageResult]: ...

    async def list_historical_indicators(
        self,
        tenant_id: TenantId,
        hazard_type: HazardType,
        stage_type: StageType,
        *,
        exclude_assessment_id: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        """Raw ``ComputationSnapshot.inputs`` dicts from every prior
        COMPLETE result of this ``(tenant, hazardType, stageType)`` —
        EWM's ``historical`` parameter (`strategies/firas/ewm.py`),
        scoped per-tenant so one tenant's computational history never
        informs another's weights.
        """
        ...

    async def list_all_indicators_by_assessment(
        self, tenant_id: TenantId, hazard_type: HazardType, *, limit: int = 200
    ) -> list[dict]:
        """One merged ``{indicator_code: value}`` dict per assessment,
        combining every one of that assessment's COMPLETE stages'
        ``ComputationSnapshot.inputs`` (across ALL stage types, unlike
        ``list_historical_indicators``'s single-stage scope) — Sprint A's
        real ``PredictionDataProvider`` reads these as its observation
        rows, since a variable selected for correlation/MLR may come from
        any stage (e.g. a Hazard raw input alongside a Risk-stage derived
        index), all within one real assessment's history.
        """
        ...

    async def next_version(
        self, tenant_id: TenantId, assessment_id: str, stage_type: StageType
    ) -> int: ...

    async def save(self, stage_result: StageResult) -> None: ...


class RiskLayerRepository(Protocol):
    """Sprint C — one repository for the new ``RiskLayer`` aggregate,
    same "generic per-(hazard,stage) design, get_latest wins" shape as
    ``StageResultRepository`` above."""

    async def get_by_id(self, risk_layer_id: RiskLayerId) -> RiskLayer | None: ...

    async def get_latest(
        self, tenant_id: TenantId, assessment_id: str, stage_type: StageType
    ) -> RiskLayer | None: ...

    async def next_version(
        self, tenant_id: TenantId, assessment_id: str, stage_type: StageType
    ) -> int: ...

    async def save(self, risk_layer: RiskLayer) -> None: ...
