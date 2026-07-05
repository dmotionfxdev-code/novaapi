"""SQLAlchemy ORM model for the ``reporting`` logical schema. Persistence
representation only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from georisk.db import schemas
from georisk.db.base import Base

_SCHEMA = schemas.REPORTING


class ReportModel(Base):
    __tablename__ = "report"
    __table_args__ = (
        Index("ix_report_assessment", "assessment_id"),
        Index("ix_report_tenant_assessment_version", "tenant_id", "assessment_id", "version"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Soft reference — assessment is a peer context (import-linter's
    # independence contract); never a declared FK.
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    issued_by: Mapped[str] = mapped_column(String(200), nullable=False)
    assessment_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    risk_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    predictor_summary: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    dataset_provenance: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    validation_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    formula_versions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    strategy_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    finalized_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
