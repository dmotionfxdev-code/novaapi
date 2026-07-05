"""Maps between Geospatial's domain entities and their SQLAlchemy ORM
representations. Free functions, not methods on either side (same
pattern as every prior context).
"""

from __future__ import annotations

import uuid as uuid_module

from georisk.contexts.geospatial.domain.entities import AreaOfInterest, SamplingCampaign
from georisk.contexts.geospatial.domain.value_objects import (
    AllocationMethod,
    AoiId,
    AoiMetadata,
    AoiSource,
    AoiStatus,
    BoundingBox,
    Centroid,
    Geometry,
    OutputFormat,
    SamplePoint,
    SamplePointId,
    SamplingCampaignId,
    SamplingCampaignStatus,
    SamplingMethod,
    SamplingStrategy,
    Stratum,
)
from georisk.contexts.geospatial.infrastructure.models import (
    AreaOfInterestModel,
    SamplingCampaignModel,
)
from georisk.contexts.identity.domain.value_objects import TenantId


def aoi_to_domain(model: AreaOfInterestModel) -> AreaOfInterest:
    return AreaOfInterest(
        id=AoiId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        assessment_id=str(model.assessment_id),
        version=model.version,
        status=AoiStatus(model.status),
        geometry=Geometry(geojson=model.geometry),
        metadata=AoiMetadata(
            name=model.metadata_name,
            source=AoiSource(model.metadata_source),
            notes=model.metadata_notes,
        ),
        area_m2=model.area_m2,
        perimeter_m=model.perimeter_m,
        centroid=Centroid(longitude=model.centroid_longitude, latitude=model.centroid_latitude),
        bbox=BoundingBox(**model.bbox),
        created_by=model.created_by,
        created_at=model.created_at,
    )


def apply_aoi_to_model(entity: AreaOfInterest, model: AreaOfInterestModel) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.assessment_id = uuid_module.UUID(entity.assessment_id)
    model.version = entity.version
    model.status = entity.status.value
    model.geometry = entity.geometry.geojson
    model.metadata_name = entity.metadata.name
    model.metadata_source = entity.metadata.source.value
    model.metadata_notes = entity.metadata.notes
    model.area_m2 = entity.area_m2
    model.perimeter_m = entity.perimeter_m
    model.centroid_longitude = entity.centroid.longitude
    model.centroid_latitude = entity.centroid.latitude
    model.bbox = {
        "min_lon": entity.bbox.min_lon,
        "min_lat": entity.bbox.min_lat,
        "max_lon": entity.bbox.max_lon,
        "max_lat": entity.bbox.max_lat,
    }
    model.created_by = entity.created_by
    model.created_at = entity.created_at


def _strategy_to_json(strategy: SamplingStrategy) -> dict:
    return {
        "method": strategy.method.value,
        "sample_size": strategy.sample_size,
        "min_per_class": strategy.min_per_class,
        "allocation_method": strategy.allocation_method.value,
        "random_seed": strategy.random_seed,
        "coordinate_system": strategy.coordinate_system,
        "output_formats": sorted(fmt.value for fmt in strategy.output_formats),
        "include_geometry": strategy.include_geometry,
        "include_class_label": strategy.include_class_label,
        "include_pixel_values": strategy.include_pixel_values,
    }


def _strategy_from_json(data: dict) -> SamplingStrategy:
    return SamplingStrategy(
        method=SamplingMethod(data["method"]),
        sample_size=data["sample_size"],
        min_per_class=data["min_per_class"],
        allocation_method=AllocationMethod(data["allocation_method"]),
        random_seed=data["random_seed"],
        coordinate_system=data["coordinate_system"],
        output_formats=frozenset(OutputFormat(fmt) for fmt in data["output_formats"]),
        include_geometry=data["include_geometry"],
        include_class_label=data["include_class_label"],
        include_pixel_values=data["include_pixel_values"],
    )


def sampling_campaign_to_domain(model: SamplingCampaignModel) -> SamplingCampaign:
    return SamplingCampaign(
        id=SamplingCampaignId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        assessment_id=str(model.assessment_id),
        aoi_id=AoiId(value=model.aoi_id),
        name=model.name,
        status=SamplingCampaignStatus(model.status),
        strategy=_strategy_from_json(model.strategy),
        strata=tuple(Stratum(label=s["label"], proportion=s["proportion"]) for s in model.strata),
        sample_points=tuple(
            SamplePoint(
                id=SamplePointId.from_string(p["id"]),
                longitude=p["longitude"],
                latitude=p["latitude"],
                stratum=p.get("stratum"),
            )
            for p in model.sample_points
        ),
        created_by=model.created_by,
        created_at=model.created_at,
    )


def apply_sampling_campaign_to_model(
    entity: SamplingCampaign, model: SamplingCampaignModel
) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.assessment_id = uuid_module.UUID(entity.assessment_id)
    model.aoi_id = entity.aoi_id.value
    model.name = entity.name
    model.status = entity.status.value
    model.strategy = _strategy_to_json(entity.strategy)
    model.strata = [{"label": s.label, "proportion": s.proportion} for s in entity.strata]
    model.sample_points = [
        {
            "id": str(p.id),
            "longitude": p.longitude,
            "latitude": p.latitude,
            "stratum": p.stratum,
        }
        for p in entity.sample_points
    ]
    model.created_by = entity.created_by
    model.created_at = entity.created_at
