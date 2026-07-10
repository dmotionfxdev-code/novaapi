"""The ``StageResult`` aggregate (Domain Model §1 row 11) — the Analysis
Engine's sole aggregate root. "A stage result is versioned evidence,
computed from a snapshot of inputs, for one stage of one assessment"
(Domain Model §4). Immutable once created — a re-run creates a new
``version`` for the same ``(assessment_id, hazard_type, stage_type)``
triple, never overwrites (Domain Model §1 row 11); the repository never
exposes an update path, only ``save`` of a brand-new row.

Nothing here imports from ``contexts.assessment`` or
``contexts.validation`` — structurally enforced by the import-linter's
peer-independence contract, the same guarantee ``ValidationRun`` (Sprint 4)
already relies on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from georisk.contexts.analysis.domain.events import (
    RiskLayerGenerated,
    StageResultComputed,
    StageResultFailed,
)
from georisk.contexts.analysis.domain.value_objects import (
    ComputationSnapshot,
    ConfidenceTier,
    HazardType,
    IndicatorSet,
    RiskLayerId,
    StageResultId,
    StageResultStatus,
    StageType,
)
from georisk.contexts.identity.domain.value_objects import TenantId


@dataclass(slots=True)
class StageResult:
    id: StageResultId
    tenant_id: TenantId
    # Soft, plain-string cross-context reference — assessment is a peer
    # context (import-linter's independence contract).
    assessment_id: str
    hazard_type: HazardType
    stage_type: StageType
    version: int
    status: StageResultStatus
    indicators: IndicatorSet | None
    confidence_tier: ConfidenceTier | None
    snapshot: ComputationSnapshot
    error: str | None
    issued_by: str
    created_at: datetime
    # Sprint 5.2 (GEORISK_SCOPE_REALIGNMENT.md §6): which HazardStrategy
    # package, and which specific formula within it, produced this result —
    # so a result computed under a since-corrected formula (e.g. FIRAS's
    # pre-realignment additive Risk / equal-weight Vulnerability) stays
    # traceable to exactly that formula generation even after the platform
    # moves on. Always known on a COMPLETE result (a calculator was
    # resolved and ran); may be None on a FAILED result if resolution
    # itself failed before any strategy/calculator was found.
    strategy_version: str | None
    formula_version: str | None
    schema_version: int = field(default=1)

    @classmethod
    def complete(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        hazard_type: HazardType,
        stage_type: StageType,
        version: int,
        indicators: IndicatorSet,
        confidence_tier: ConfidenceTier,
        snapshot: ComputationSnapshot,
        issued_by: str,
        strategy_version: str,
        formula_version: str,
    ) -> tuple[StageResult, StageResultComputed]:
        result = cls(
            id=StageResultId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            hazard_type=hazard_type,
            stage_type=stage_type,
            version=version,
            status=StageResultStatus.COMPLETE,
            indicators=indicators,
            confidence_tier=confidence_tier,
            snapshot=snapshot,
            error=None,
            issued_by=issued_by,
            created_at=datetime.now(UTC),
            strategy_version=strategy_version,
            formula_version=formula_version,
        )
        event = StageResultComputed(
            stage_result_id=str(result.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type=hazard_type.value,
            stage_type=stage_type.value,
            version=version,
            confidence_tier=confidence_tier.value,
            indicators=indicators.as_dict(),
            strategy_version=strategy_version,
            formula_version=formula_version,
        )
        return result, event

    @classmethod
    def failed(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        hazard_type: HazardType,
        stage_type: StageType,
        version: int,
        snapshot: ComputationSnapshot,
        error: str,
        issued_by: str,
        strategy_version: str | None = None,
        formula_version: str | None = None,
    ) -> tuple[StageResult, StageResultFailed]:
        result = cls(
            id=StageResultId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            hazard_type=hazard_type,
            stage_type=stage_type,
            version=version,
            status=StageResultStatus.FAILED,
            indicators=None,
            confidence_tier=None,
            snapshot=snapshot,
            error=error,
            issued_by=issued_by,
            created_at=datetime.now(UTC),
            strategy_version=strategy_version,
            formula_version=formula_version,
        )
        event = StageResultFailed(
            stage_result_id=str(result.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type=hazard_type.value,
            stage_type=stage_type.value,
            version=version,
            error=error,
        )
        return result, event


@dataclass(slots=True)
class RiskLayer:
    """Sprint C — a real spatial artifact derived from one completed RISK
    ``StageResult`` plus a genuinely-uploaded (Sprint B) geometry
    dataset. Immutable once generated, same "insert-only, latest version
    wins" discipline as ``StageResult``/``Dataset``/``PredictionRun`` — a
    regeneration (e.g. the RISK stage re-runs with new inputs) creates a
    new version, never overwrites, so a prior version's exact GeoJSON
    stays auditable.

    ``dataset_id`` is a soft, plain-string cross-context reference to Data
    Acquisition's ``Dataset`` (the geometry source) — same convention as
    ``assessment_id``'s reference to the peer Assessment context.
    ``geojson`` is the complete, real RFC 7946 ``FeatureCollection`` this
    aggregate exists to serve; nothing about its features is fabricated
    (every one traces back to a real uploaded Shapefile feature — see
    ``infrastructure/risk_layer_generator.py``).
    """

    id: RiskLayerId
    tenant_id: TenantId
    assessment_id: str
    hazard_type: HazardType
    stage_type: StageType
    stage_result_id: StageResultId
    dataset_id: str
    version: int
    geometry_type: str
    feature_count: int
    bounding_box: tuple[float, float, float, float]
    crs: str
    risk_index: float
    risk_level: str
    classification: str
    formula_version: str
    geojson: dict
    generated_at: datetime

    @classmethod
    def generate(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        hazard_type: HazardType,
        stage_type: StageType,
        stage_result_id: StageResultId,
        dataset_id: str,
        version: int,
        geometry_type: str,
        feature_count: int,
        bounding_box: tuple[float, float, float, float],
        crs: str,
        risk_index: float,
        risk_level: str,
        classification: str,
        formula_version: str,
        geojson: dict,
    ) -> tuple[RiskLayer, RiskLayerGenerated]:
        layer = cls(
            id=RiskLayerId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            hazard_type=hazard_type,
            stage_type=stage_type,
            stage_result_id=stage_result_id,
            dataset_id=dataset_id,
            version=version,
            geometry_type=geometry_type,
            feature_count=feature_count,
            bounding_box=bounding_box,
            crs=crs,
            risk_index=risk_index,
            risk_level=risk_level,
            classification=classification,
            formula_version=formula_version,
            geojson=geojson,
            generated_at=datetime.now(UTC),
        )
        event = RiskLayerGenerated(
            risk_layer_id=str(layer.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            hazard_type=hazard_type.value,
            stage_type=stage_type.value,
            dataset_id=dataset_id,
            feature_count=feature_count,
            version=version,
        )
        return layer, event
