"""SQLAlchemy ORM model for the ``validation`` logical schema
(Infrastructure Architecture §2). Persistence representation only — the
repository maps this to/from the domain entity; nothing outside
``infrastructure/`` should import this model directly.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from georisk.db import schemas
from georisk.db.base import Base

_SCHEMA = schemas.VALIDATION


class ValidationRunModel(Base):
    __tablename__ = "validation_run"
    __table_args__ = (
        Index("ix_validation_run_tenant_assessment", "tenant_id", "assessment_id"),
        Index("ix_validation_run_tenant_created_at", "tenant_id", "created_at"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    # References identity.tenant.id — soft reference, no cross-schema FK
    # (Domain Model §1/§7), same reasoning as every other cross-context id
    # in this codebase.
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # References assessment.assessment.id — soft reference; assessment and
    # validation are independent peer contexts (import-linter contract),
    # so this is a plain UUID column, never a declared ForeignKey.
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Opaque reference to whatever's being judged (a StageResult/Prediction
    # id in the full design) — arbitrary string, not necessarily a UUID
    # (this sprint's stub subjects are e.g. "stub:<assessmentId>:RISK").
    subject_id: Mapped[str] = mapped_column(String(200), nullable=False)
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Sprint 10: every pre-existing row is unambiguously CLASSIFICATION
    # (no other mode existed before this column) — server_default backfills
    # that known fact, not a guess (contrast with formula_version's NULL-
    # means-"not tracked" precedent in Analysis).
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="CLASSIFICATION"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    thresholds: Mapped[dict] = mapped_column(JSONB, nullable=False)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    regression_metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String(10), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
