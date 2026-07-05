"""Commands for the Geospatial context (Application Layer §1's Geospatial
table: ``DefineAoi``/``ReviseAoi``, ``ConfigureSamplingCampaign``,
``GenerateSamplePoints``). Plain dataclasses — no behavior, just the
data a handler needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DefineOrReviseAoiCommand:
    """Handles both ``DefineAoi`` (no active AOI exists yet for this
    assessment) and ``ReviseAoi`` (one already does) — the handler decides
    which per Application Layer §1's note that these are the same
    ``POST /assessments/{id}/aoi`` endpoint in the API Resource Model."""

    tenant_id: str
    assessment_id: str
    source: str
    geojson: dict
    name: str
    notes: str
    issued_by: str


@dataclass(frozen=True, slots=True)
class ConfigureSamplingCampaignCommand:
    tenant_id: str
    assessment_id: str
    aoi_id: str
    name: str
    method: str
    sample_size: int
    strata: tuple[dict, ...] = field(default_factory=tuple)
    allocation_method: str = "PROPORTIONAL"
    output_formats: tuple[str, ...] = ("GEOJSON", "CSV")
    include_geometry: bool = True
    include_class_label: bool = True
    include_pixel_values: bool = False
    random_seed: int = 12345
    issued_by: str = ""


@dataclass(frozen=True, slots=True)
class GenerateSamplePointsCommand:
    tenant_id: str
    sampling_campaign_id: str
    issued_by: str
