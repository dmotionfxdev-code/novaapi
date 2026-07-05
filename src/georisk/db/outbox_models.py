"""The transactional outbox table (Infrastructure Architecture §8/§9).

Platform-wide, not context-specific — every bounded context's command
handlers append rows here, in the same transaction as their aggregate save,
as the durable record of "what happened." No relay/consumer exists until
Roadmap Sprint 3; until then, rows accumulate here unread, which is
harmless and exactly the incremental sequencing the Roadmap describes.

Identity (Roadmap Sprint 1) is the first real producer — every identity
command handler that changes something appends an event here, which is
what satisfies this sprint's "Audit Events" requirement: a durable,
queryable record of every significant identity action (registrations,
logins, role changes, status changes), inspectable today via a direct
query, and automatically became Sprint 3's event-relay source and Sprint
12's Audit context's data source once those exist — no rework needed then.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from georisk.db.base import Base


class OutboxEventModel(Base):
    __tablename__ = "outbox_event"
    __table_args__ = (
        Index("ix_outbox_event_aggregate", "aggregate_type", "aggregate_id", "sequence_number"),
        Index("ix_outbox_event_unrelayed", "relayed_at"),
        Index("ix_outbox_event_tenant", "tenant_id", "occurred_at"),
        {"schema": "public"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Monotonic per (aggregate_type, aggregate_id) — the per-aggregate
    # ordering guarantee Application Layer §8 depends on. Assigned by the
    # writer (OutboxWriter), not the database, since it must be scoped per
    # aggregate instance, not globally auto-incrementing.
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)
    relayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
