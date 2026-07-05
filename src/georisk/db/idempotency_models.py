"""Idempotency dedupe store (Application Layer §11) — platform-wide, not
context-specific, same rationale as ``db/outbox_models.py``: built once,
generically, rather than reimplemented per context as each one needs it.
Identity (Roadmap Sprint 1) is the first consumer.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from georisk.db.base import Base


class IdempotencyKeyModel(Base):
    __tablename__ = "idempotency_key"
    __table_args__ = ({"schema": "public"},)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Unique per (idempotency_key, command_type) — the same client-supplied
    # key is scoped to one command type, so a collision across unrelated
    # commands can't accidentally share a cached result.
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    command_type: Mapped[str] = mapped_column(String(150), nullable=False)
    response_body: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
