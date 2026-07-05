"""SQLAlchemy ORM model for the ``assessment`` logical schema
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

_SCHEMA = schemas.ASSESSMENT


class AssessmentModel(Base):
    __tablename__ = "assessment"
    __table_args__ = (
        Index("ix_assessment_tenant_status", "tenant_id", "status"),
        Index("ix_assessment_tenant_created_at", "tenant_id", "created_at"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    # References identity.tenant.id, but deliberately NOT declared as a
    # cross-schema ForeignKey — bounded contexts reference each other only
    # by ID value (Domain Model §1/§7), never by a database-level FK that
    # would couple the two schemas' migration histories together.
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hazard_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # References identity.user.id — same reasoning as tenant_id above.
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cancellation_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Workflow Engine (Roadmap Sprint 3). References
    # assessment.workflow_template.id — same "reference by value, not a
    # cross-schema FK" posture, even though it happens to be the same
    # schema here, for consistency with every other soft reference in this
    # model. ``workflow_progress`` is Domain Model §1's WorkflowProgress
    # value object, serialized as JSONB (mappers.py owns the shape) — an
    # embedded projection on this aggregate, not a separate table.
    workflow_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    workflow_progress: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class WorkflowTemplateModel(Base):
    """A global, platform-owned catalog table — no ``tenant_id`` column,
    same reasoning as Identity's ``Role``/``Permission`` reference tables
    (Sprint 1): templates are authored once and read by every tenant, not
    owned by any one of them.
    """

    __tablename__ = "workflow_template"
    __table_args__ = (
        Index("ix_workflow_template_hazard_status", "hazard_type", "status"),
        {"schema": _SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    hazard_type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    stage_definitions: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
