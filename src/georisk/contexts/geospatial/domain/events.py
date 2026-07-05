"""Geospatial domain events — appended to the outbox within the same
transaction as the aggregate they describe (matching every prior
context's pattern). ``AoiAttached`` is the exact event name Domain Model
§5 gives Assessment to react to; it is emitted here, by Geospatial, the
supplier side of the Customer/Supplier relationship (Domain Model §7) —
nothing in this module imports from ``contexts.assessment``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class AoiAttached:
    event_type: ClassVar[str] = "geospatial.AoiAttached"
    aoi_id: str
    tenant_id: str
    assessment_id: str
    version: int

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class AoiRevised:
    event_type: ClassVar[str] = "geospatial.AoiRevised"
    aoi_id: str
    tenant_id: str
    assessment_id: str
    version: int
    superseded_aoi_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class SamplingCampaignConfigured:
    event_type: ClassVar[str] = "geospatial.SamplingCampaignConfigured"
    sampling_campaign_id: str
    tenant_id: str
    assessment_id: str
    aoi_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class SamplePointsGenerated:
    event_type: ClassVar[str] = "geospatial.SamplePointsGenerated"
    sampling_campaign_id: str
    tenant_id: str
    sample_count: int

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}
