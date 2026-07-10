"""Pydantic response models — independent of the SQLAlchemy models and
domain entities (Architecture Redesign §9). Same pattern as every prior
context. Read-only API: no request schemas — ``StageResult`` is never
created via this interface, only produced by the Workflow-Engine-triggered
``RecordStageResultCommand`` pipeline (composition root).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from georisk.contexts.analysis.domain.entities import RiskLayer, StageResult


class IndicatorResponse(BaseModel):
    code: str
    value: float
    unit: str
    sub_index: str | None


class StageResultResponse(BaseModel):
    id: str
    tenant_id: str
    assessment_id: str
    hazard_type: str
    stage_type: str
    version: int
    status: str
    confidence_tier: str | None
    error: str | None
    issued_by: str
    created_at: datetime
    strategy_version: str | None
    formula_version: str | None
    indicators: list[IndicatorResponse]

    @classmethod
    def from_domain(cls, result: StageResult) -> StageResultResponse:
        return cls(
            id=str(result.id),
            tenant_id=str(result.tenant_id),
            assessment_id=result.assessment_id,
            hazard_type=result.hazard_type.value,
            stage_type=result.stage_type.value,
            version=result.version,
            status=result.status.value,
            confidence_tier=result.confidence_tier.value
            if result.confidence_tier is not None
            else None,
            error=result.error,
            issued_by=result.issued_by,
            created_at=result.created_at,
            strategy_version=result.strategy_version,
            formula_version=result.formula_version,
            indicators=(
                [
                    IndicatorResponse(
                        code=i.code, value=i.value, unit=i.unit, sub_index=i.sub_index
                    )
                    for i in result.indicators.indicators
                ]
                if result.indicators is not None
                else []
            ),
        )


class StageResultListResponse(BaseModel):
    data: list[StageResultResponse]

    @classmethod
    def from_domain(cls, results: list[StageResult]) -> StageResultListResponse:
        return cls(data=[StageResultResponse.from_domain(r) for r in results])


class RasterMetadataResponse(BaseModel):
    """Sprint C requirement #2: "If raster generation is already
    technically possible using the current dependencies, expose raster
    metadata as well. If not, document why honestly." It is not: this
    platform's only GIS-capable dependencies (``pyogrio``, ``shapely``)
    are OGR/GEOS vector-side bindings — neither wraps GDAL's raster (GA)
    API, and no ``rasterio``/raw ``osgeo.gdal`` dependency exists anywhere
    in this codebase (Sprint 14 already documented the identical "no
    GDAL/rasterio" limitation for remote-sensing feature extraction).
    Genuine raster (GeoTIFF/pixel-grid) generation would need a new
    dependency this sprint was not asked to add. This response is
    honestly a documentation stub, not fabricated raster output —
    ``available`` is always ``False`` today.
    """

    available: bool
    reason: str
    suggested_bounding_box: tuple[float, float, float, float]
    suggested_crs: str


class RiskLayerResponse(BaseModel):
    id: str
    assessment_id: str
    hazard_type: str
    stage_type: str
    stage_result_id: str
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
    generated_at: datetime
    raster_metadata: RasterMetadataResponse

    @classmethod
    def from_domain(cls, layer: RiskLayer) -> RiskLayerResponse:
        return cls(
            id=str(layer.id),
            assessment_id=layer.assessment_id,
            hazard_type=layer.hazard_type.value,
            stage_type=layer.stage_type.value,
            stage_result_id=str(layer.stage_result_id),
            dataset_id=layer.dataset_id,
            version=layer.version,
            geometry_type=layer.geometry_type,
            feature_count=layer.feature_count,
            bounding_box=layer.bounding_box,
            crs=layer.crs,
            risk_index=layer.risk_index,
            risk_level=layer.risk_level,
            classification=layer.classification,
            formula_version=layer.formula_version,
            generated_at=layer.generated_at,
            raster_metadata=RasterMetadataResponse(
                available=False,
                reason=(
                    "This platform's GIS dependencies (pyogrio, shapely) are vector-only "
                    "(OGR/GEOS) — no rasterio/GDAL-raster binding exists, so no pixel grid "
                    "is generated. A future sprint adding rasterio could rasterize this "
                    "layer's bounding box at a chosen resolution/CRS."
                ),
                suggested_bounding_box=layer.bounding_box,
                suggested_crs=layer.crs,
            ),
        )


class RiskSummaryResponse(BaseModel):
    """The non-spatial companion to ``RiskLayerResponse`` — just the
    computed-risk facts, no geometry/GeoJSON at all."""

    assessment_id: str
    hazard_type: str
    stage_type: str
    risk_index: float
    risk_level: str
    classification: str
    formula_version: str
    generated_at: datetime

    @classmethod
    def from_domain(cls, layer: RiskLayer) -> RiskSummaryResponse:
        return cls(
            assessment_id=layer.assessment_id,
            hazard_type=layer.hazard_type.value,
            stage_type=layer.stage_type.value,
            risk_index=layer.risk_index,
            risk_level=layer.risk_level,
            classification=layer.classification,
            formula_version=layer.formula_version,
            generated_at=layer.generated_at,
        )


class RiskLayerGeoJsonResponse(BaseModel):
    """Not actually used as a FastAPI ``response_model`` (the geojson
    route returns a raw ``Response`` with the stored FeatureCollection
    body directly, per requirement #5's "keep responses streaming-
    friendly" — wrapping it in a Pydantic envelope would mean re-encoding
    an already-JSON blob). Kept here only as documentation of the exact
    shape a client receives: a bare RFC 7946 ``FeatureCollection``, e.g.
    ``{"type": "FeatureCollection", "features": [...]}``.
    """

    type: str
    features: list[dict[str, Any]]
