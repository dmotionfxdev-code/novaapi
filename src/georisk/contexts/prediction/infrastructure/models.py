"""SQLAlchemy ORM model for the ``prediction`` logical schema. Persistence
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

_SCHEMA = schemas.PREDICTION


class PredictionRunModel(Base):
    __tablename__ = "prediction_run"
    __table_args__ = (
        Index("ix_prediction_run_assessment", "assessment_id"),
        Index(
            "ix_prediction_run_tenant_selection_method",
            "tenant_id",
            "variable_selection_id",
            "method",
            "version",
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Soft references — assessment/geospatial/data_acquisition are peer
    # contexts (import-linter's independence contract); never declared FKs.
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    variable_selection_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sampling_campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    method: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    model_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    correlation_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    regression_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    issued_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
