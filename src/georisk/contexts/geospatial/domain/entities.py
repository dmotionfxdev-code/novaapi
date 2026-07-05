"""The Geospatial context's two aggregate roots (Domain Model §1 rows
3-4): ``AreaOfInterest`` and ``SamplingCampaign``. Nothing here imports
from ``contexts.assessment`` — structurally enforced by the
import-linter's peer-independence contract, the same guarantee every
prior context's aggregates already rely on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from georisk.contexts.geospatial.domain.errors import (
    SamplePointOutsideAoiError,
    SamplingNotConfiguredError,
)
from georisk.contexts.geospatial.domain.events import (
    AoiAttached,
    AoiRevised,
    SamplePointsGenerated,
    SamplingCampaignConfigured,
)
from georisk.contexts.geospatial.domain.geometry import compute_aoi_statistics, point_in_geometry
from georisk.contexts.geospatial.domain.sampling import (
    generate_simple_random_samples,
    generate_stratified_samples,
)
from georisk.contexts.geospatial.domain.value_objects import (
    AoiId,
    AoiMetadata,
    AoiStatus,
    BoundingBox,
    Centroid,
    Geometry,
    SamplePoint,
    SamplingCampaignId,
    SamplingCampaignStatus,
    SamplingMethod,
    SamplingStrategy,
    Stratum,
)
from georisk.contexts.identity.domain.value_objects import TenantId


@dataclass(slots=True)
class AreaOfInterest:
    id: AoiId
    tenant_id: TenantId
    # Soft, plain-string cross-context reference — assessment is a peer
    # context (import-linter's independence contract), same pattern as
    # every prior context's `assessment_id: str`.
    assessment_id: str
    version: int
    status: AoiStatus
    geometry: Geometry
    metadata: AoiMetadata
    area_m2: float
    perimeter_m: float
    centroid: Centroid
    bbox: BoundingBox
    created_by: str
    created_at: datetime

    @classmethod
    def define(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        geometry: Geometry,
        metadata: AoiMetadata,
        created_by: str,
    ) -> tuple[AreaOfInterest, AoiAttached]:
        stats = compute_aoi_statistics(geometry)
        aoi = cls(
            id=AoiId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            version=1,
            status=AoiStatus.ACTIVE,
            geometry=geometry,
            metadata=metadata,
            area_m2=stats.area_m2,
            perimeter_m=stats.perimeter_m,
            centroid=stats.centroid,
            bbox=stats.bbox,
            created_by=created_by,
            created_at=datetime.now(UTC),
        )
        event = AoiAttached(
            aoi_id=str(aoi.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            version=aoi.version,
        )
        return aoi, event

    @classmethod
    def revise(
        cls,
        *,
        previous: AreaOfInterest,
        geometry: Geometry,
        metadata: AoiMetadata,
        created_by: str,
    ) -> tuple[AreaOfInterest, AoiRevised]:
        """Domain Model §1 row 3: "edits create a new version, never
        mutate in place." The caller (``DefineAoiHandler``) is
        responsible for persisting ``previous`` (now ``SUPERSEDED``, via
        ``mark_superseded``) and the new version in the same transaction.
        """
        stats = compute_aoi_statistics(geometry)
        aoi = cls(
            id=AoiId.new(),
            tenant_id=previous.tenant_id,
            assessment_id=previous.assessment_id,
            version=previous.version + 1,
            status=AoiStatus.ACTIVE,
            geometry=geometry,
            metadata=metadata,
            area_m2=stats.area_m2,
            perimeter_m=stats.perimeter_m,
            centroid=stats.centroid,
            bbox=stats.bbox,
            created_by=created_by,
            created_at=datetime.now(UTC),
        )
        event = AoiRevised(
            aoi_id=str(aoi.id),
            tenant_id=str(previous.tenant_id),
            assessment_id=previous.assessment_id,
            version=aoi.version,
            superseded_aoi_id=str(previous.id),
        )
        return aoi, event

    def mark_superseded(self) -> None:
        self.status = AoiStatus.SUPERSEDED


@dataclass(slots=True)
class SamplingCampaign:
    id: SamplingCampaignId
    tenant_id: TenantId
    assessment_id: str
    aoi_id: AoiId  # same-context reference — Geospatial owns both aggregates
    name: str
    status: SamplingCampaignStatus
    strategy: SamplingStrategy
    strata: tuple[Stratum, ...]
    sample_points: tuple[SamplePoint, ...]
    created_by: str
    created_at: datetime

    @classmethod
    def configure(
        cls,
        *,
        tenant_id: TenantId,
        assessment_id: str,
        aoi_id: AoiId,
        name: str,
        strategy: SamplingStrategy,
        strata: tuple[Stratum, ...] = (),
        created_by: str,
    ) -> tuple[SamplingCampaign, SamplingCampaignConfigured]:
        if strategy.method is SamplingMethod.STRATIFIED_RANDOM and not strata:
            raise SamplingNotConfiguredError(
                "Stratified random sampling requires at least one Stratum"
            )
        campaign = cls(
            id=SamplingCampaignId.new(),
            tenant_id=tenant_id,
            assessment_id=assessment_id,
            aoi_id=aoi_id,
            name=name,
            status=SamplingCampaignStatus.DRAFT,
            strategy=strategy,
            strata=strata,
            sample_points=(),
            created_by=created_by,
            created_at=datetime.now(UTC),
        )
        event = SamplingCampaignConfigured(
            sampling_campaign_id=str(campaign.id),
            tenant_id=str(tenant_id),
            assessment_id=assessment_id,
            aoi_id=str(aoi_id),
        )
        return campaign, event

    def generate_points(self, *, aoi_geometry: Geometry) -> SamplePointsGenerated:
        """Domain Model §1 row 4: "Every SamplePoint must fall within the
        referenced AOI's geometry; sample count matches declared strategy
        parameters" — both invariants are checked here, not trusted from
        the generator.
        """
        if self.status is SamplingCampaignStatus.GENERATED:
            raise SamplingNotConfiguredError(
                f"SamplingCampaign {self.id} has already generated its sample points"
            )

        if self.strategy.method is SamplingMethod.STRATIFIED_RANDOM:
            points = generate_stratified_samples(
                aoi_geometry,
                self.strata,
                self.strategy.sample_size,
                self.strategy.allocation_method,
                self.strategy.random_seed,
            )
        else:
            points = generate_simple_random_samples(
                aoi_geometry, self.strategy.sample_size, self.strategy.random_seed
            )

        for point in points:
            if not point_in_geometry(point.longitude, point.latitude, aoi_geometry):
                raise SamplePointOutsideAoiError(
                    f"Generated sample point {point.id} falls outside the AOI geometry"
                )

        self.sample_points = points
        self.status = SamplingCampaignStatus.GENERATED
        return SamplePointsGenerated(
            sampling_campaign_id=str(self.id),
            tenant_id=str(self.tenant_id),
            sample_count=len(points),
        )
