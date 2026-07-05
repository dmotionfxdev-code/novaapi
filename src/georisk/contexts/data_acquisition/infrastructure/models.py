"""SQLAlchemy ORM models for the ``data_acquisition`` logical schema.
Persistence representation only.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from georisk.db import schemas
from georisk.db.base import Base

_SCHEMA = schemas.DATA_ACQUISITION


class DatasetSourceModel(Base):
    __tablename__ = "dataset_source"
    __table_args__ = (
        Index("ix_dataset_source_tenant", "tenant_id"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    # Nullable: None = a platform-wide source every tenant can reference.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DatasetModel(Base):
    __tablename__ = "dataset"
    __table_args__ = (
        Index("ix_dataset_tenant_name_version", "tenant_id", "metadata_name", "version"),
        Index("ix_dataset_tenant_status", "tenant_id", "status"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    dataset_source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)

    # --- DatasetMetadata, flattened (Sprint 7's required metadata fields) ---
    metadata_name: Mapped[str] = mapped_column(String(200), nullable=False)
    dataset_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    spatial_resolution_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    temporal_resolution: Mapped[str | None] = mapped_column(String(20), nullable=True)
    crs: Mapped[str] = mapped_column(String(30), nullable=False)
    spatial_coverage: Mapped[str] = mapped_column(String(500), nullable=False)
    temporal_coverage_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    temporal_coverage_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    processing_method: Mapped[str] = mapped_column(String(30), nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(200), nullable=True)

    provenance: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    readiness: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    catalogued_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PredictorVariableModel(Base):
    __tablename__ = "predictor_variable"
    __table_args__ = (
        Index("ix_predictor_variable_tenant_category", "tenant_id", "category"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    variable_role: Mapped[str] = mapped_column(String(20), nullable=False)
    data_type: Mapped[str] = mapped_column(String(20), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    value_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_required_for_mlr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    linked_dataset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VariableSelectionModel(Base):
    __tablename__ = "variable_selection"
    __table_args__ = (
        Index("ix_variable_selection_tenant", "tenant_id"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hazard_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    selected_variable_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AcquisitionJobModel(Base):
    __tablename__ = "acquisition_job"
    __table_args__ = (
        Index("ix_acquisition_job_tenant_status", "tenant_id", "status"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    source_reference: Mapped[str] = mapped_column(String, nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    dataset_source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    declared_crs: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_content_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Sprint 14: Remote Sensing Integration ---
    remote_sensing_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    aoi_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    temporal_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    temporal_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comparison_temporal_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    comparison_temporal_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_preprocessing: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    requested_indices: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    applied_preprocessing: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    extracted_features: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    skipped_features: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
