"""SQLAlchemy ORM model for the ``analysis`` logical schema (Infrastructure
Architecture §2: "``StageResultRepository`` is a single generic
implementation parameterized by ``(hazardType, stageType)``, backed by the
JSONB indicator design"). Persistence representation only.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from georisk.db import schemas
from georisk.db.base import Base

_SCHEMA = schemas.ANALYSIS


class StageResultModel(Base):
    __tablename__ = "stage_result"
    __table_args__ = (
        # The lookup every downstream calculator and the workflow
        # integration make: "give me the latest version of this
        # assessment's this stage."
        Index(
            "ix_stage_result_assessment_stage_version",
            "assessment_id",
            "stage_type",
            "version",
        ),
        # EWM's historical-observations lookup: every past COMPLETE result
        # of this (tenant, hazard_type, stage_type), across assessments.
        Index(
            "ix_stage_result_tenant_hazard_stage",
            "tenant_id",
            "hazard_type",
            "stage_type",
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Soft reference to assessment.assessment.id — assessment is a peer
    # context (import-linter's independence contract); never a declared FK.
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    hazard_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Sprint 6 (Architecture Defect, WRRAS onboarding): widened from
    # String(20) — "BURN_OCCURRENCE_PROBABILITY" is 27 characters, longer
    # than any FIRAS stage name anticipated when this column was sized.
    stage_type: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    indicators: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    confidence_tier: Mapped[str | None] = mapped_column(String(10), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Sprint 5.2: which strategy package / which formula within it produced
    # this result — nullable because a FAILED result may predate ever
    # resolving a calculator (e.g. an unregistered hazard type).
    strategy_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    formula_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class RiskLayerModel(Base):
    """Sprint C — the ``RiskLayer`` aggregate's persistence. ``geojson``
    stores the complete, real ``FeatureCollection`` as JSONB (same
    "large generated blob as one JSONB column" convention as
    ``StageResult.snapshot``/``AcquisitionJob.provenance``/Reporting's
    own frozen section snapshots) — requirement #6's "persist using
    existing storage conventions," not a new object-storage mechanism.
    """

    __tablename__ = "risk_layer"
    __table_args__ = (
        Index(
            "ix_risk_layer_assessment_stage_version",
            "assessment_id",
            "stage_type",
            "version",
        ),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    assessment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    hazard_type: Mapped[str] = mapped_column(String(20), nullable=False)
    stage_type: Mapped[str] = mapped_column(String(40), nullable=False)
    stage_result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # Soft reference to data_acquisition.dataset.id — Data Acquisition is
    # a peer context (import-linter's independence contract); never a
    # declared FK, same convention as every other cross-context reference
    # in this codebase (e.g. StageResultModel.assessment_id).
    dataset_id: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry_type: Mapped[str] = mapped_column(String(30), nullable=False)
    feature_count: Mapped[int] = mapped_column(Integer, nullable=False)
    bounding_box: Mapped[list] = mapped_column(JSONB, nullable=False)
    crs: Mapped[str] = mapped_column(String(30), nullable=False)
    risk_index: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)
    classification: Mapped[str] = mapped_column(String(50), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(50), nullable=False)
    geojson: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
