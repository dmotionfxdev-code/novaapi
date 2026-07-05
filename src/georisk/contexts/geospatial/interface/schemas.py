"""Pydantic request/response models — independent of the SQLAlchemy
models and domain entities (Architecture Redesign §9). Same pattern as
every prior context.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from georisk.contexts.geospatial.domain.entities import AreaOfInterest, SamplingCampaign


class DefineOrReviseAoiRequest(BaseModel):
    source: str
    geometry: dict
    name: str
    notes: str = ""


class AoiResponse(BaseModel):
    id: str
    tenant_id: str
    assessment_id: str
    version: int
    status: str
    geometry: dict
    name: str
    source: str
    notes: str
    area_m2: float
    perimeter_m: float
    centroid_longitude: float
    centroid_latitude: float
    bbox: dict
    created_by: str
    created_at: datetime

    @classmethod
    def from_domain(cls, aoi: AreaOfInterest) -> AoiResponse:
        return cls(
            id=str(aoi.id),
            tenant_id=str(aoi.tenant_id),
            assessment_id=aoi.assessment_id,
            version=aoi.version,
            status=aoi.status.value,
            geometry=aoi.geometry.geojson,
            name=aoi.metadata.name,
            source=aoi.metadata.source.value,
            notes=aoi.metadata.notes,
            area_m2=aoi.area_m2,
            perimeter_m=aoi.perimeter_m,
            centroid_longitude=aoi.centroid.longitude,
            centroid_latitude=aoi.centroid.latitude,
            bbox={
                "min_lon": aoi.bbox.min_lon,
                "min_lat": aoi.bbox.min_lat,
                "max_lon": aoi.bbox.max_lon,
                "max_lat": aoi.bbox.max_lat,
            },
            created_by=aoi.created_by,
            created_at=aoi.created_at,
        )


class AoiListResponse(BaseModel):
    data: list[AoiResponse]

    @classmethod
    def from_domain(cls, versions: list[AreaOfInterest]) -> AoiListResponse:
        return cls(data=[AoiResponse.from_domain(v) for v in versions])


class StratumRequest(BaseModel):
    label: str
    proportion: float


class ConfigureSamplingCampaignRequest(BaseModel):
    aoi_id: str
    name: str
    method: str = "STRATIFIED_RANDOM"
    sample_size: int = 5000
    strata: list[StratumRequest] = []
    allocation_method: str = "PROPORTIONAL"
    output_formats: list[str] = ["GEOJSON", "CSV"]
    include_geometry: bool = True
    include_class_label: bool = True
    include_pixel_values: bool = False
    random_seed: int = 12345


class SamplePointResponse(BaseModel):
    id: str
    longitude: float
    latitude: float
    stratum: str | None


class SamplingCampaignResponse(BaseModel):
    id: str
    tenant_id: str
    assessment_id: str
    aoi_id: str
    name: str
    status: str
    strategy: dict
    strata: list[StratumRequest]
    sample_count: int
    created_by: str
    created_at: datetime

    @classmethod
    def from_domain(cls, campaign: SamplingCampaign) -> SamplingCampaignResponse:
        strategy = campaign.strategy
        return cls(
            id=str(campaign.id),
            tenant_id=str(campaign.tenant_id),
            assessment_id=campaign.assessment_id,
            aoi_id=str(campaign.aoi_id),
            name=campaign.name,
            status=campaign.status.value,
            strategy={
                "method": strategy.method.value,
                "sample_size": strategy.sample_size,
                "min_per_class": strategy.min_per_class,
                "allocation_method": strategy.allocation_method.value,
                "random_seed": strategy.random_seed,
                "coordinate_system": strategy.coordinate_system,
                "output_formats": sorted(fmt.value for fmt in strategy.output_formats),
            },
            strata=[
                StratumRequest(label=s.label, proportion=s.proportion) for s in campaign.strata
            ],
            sample_count=len(campaign.sample_points),
            created_by=campaign.created_by,
            created_at=campaign.created_at,
        )


class SamplingCampaignListResponse(BaseModel):
    data: list[SamplingCampaignResponse]

    @classmethod
    def from_domain(cls, campaigns: list[SamplingCampaign]) -> SamplingCampaignListResponse:
        return cls(data=[SamplingCampaignResponse.from_domain(c) for c in campaigns])


class SamplePointListResponse(BaseModel):
    data: list[SamplePointResponse]

    @classmethod
    def from_domain(cls, campaign: SamplingCampaign) -> SamplePointListResponse:
        return cls(
            data=[
                SamplePointResponse(
                    id=str(p.id), longitude=p.longitude, latitude=p.latitude, stratum=p.stratum
                )
                for p in campaign.sample_points
            ]
        )
