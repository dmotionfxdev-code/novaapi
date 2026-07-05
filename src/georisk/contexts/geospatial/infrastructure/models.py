"""SQLAlchemy ORM models for the ``geospatial`` logical schema.

Sprint 7 scope note: ``geometry``/``bbox``/``centroid`` are stored as
plain JSONB, not native PostGIS ``geometry`` columns — see
``domain/value_objects.py``'s module docstring for why (no PostGIS
available anywhere in this platform's validation environment; upgrading
to native geometry + GiST indexing is a deferred infrastructure task, not
a blocker for AOI/Sampling domain logic).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from georisk.db import schemas
from georisk.db.base import Base

_SCHEMA = schemas.GEOSPATIAL


class AreaOfInterestModel(Base):
    __tablename__ = "aoi"
    __table_args__ = (
        Index("ix_aoi_assessment_version", "assessment_id", "version"),
        # The lookup every read query makes: "give me this assessment's
        # currently active AOI." A partial index (Infrastructure
        # Architecture §4: "partial indexes on aoi scoped to WHERE
        # status = 'ACTIVE'") would be the production-grade version of
        # this; plain composite index today, upgraded alongside the
        # native-PostGIS-geometry follow-on.
        Index("ix_aoi_tenant_assessment_status", "tenant_id", "assessment_id", "status"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Soft reference to assessment.assessment.id — assessment is a peer
    # context (import-linter's independence contract); never a declared FK.
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    geometry: Mapped[dict] = mapped_column(JSONB, nullable=False)
    metadata_name: Mapped[str] = mapped_column(String(200), nullable=False)
    metadata_source: Mapped[str] = mapped_column(String(20), nullable=False)
    metadata_notes: Mapped[str] = mapped_column(String, nullable=False, default="")
    area_m2: Mapped[float] = mapped_column(Float, nullable=False)
    perimeter_m: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    centroid_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    bbox: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SamplingCampaignModel(Base):
    __tablename__ = "sampling_campaign"
    __table_args__ = (
        Index("ix_sampling_campaign_tenant_assessment", "tenant_id", "assessment_id"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    aoi_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    strategy: Mapped[dict] = mapped_column(JSONB, nullable=False)
    strata: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    sample_points: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
