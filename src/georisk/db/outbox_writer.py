"""Helper for appending an event to the outbox within a command handler's
existing transaction (Application Layer §2 pipeline step 8; Infrastructure
Architecture §9). Never commits — the caller's own session/transaction
boundary owns that, consistent with the one-transaction-per-command rule.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.db.outbox_models import OutboxEventModel


async def append_event(
    session: AsyncSession,
    *,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: dict,
    tenant_id: uuid.UUID | None,
) -> OutboxEventModel:
    """Appends one event, assigning the next monotonic sequence number for
    this specific aggregate instance (not a global sequence — Application
    Layer §8's ordering guarantee is scoped per aggregate).
    """
    next_seq = await session.scalar(
        select(func.coalesce(func.max(OutboxEventModel.sequence_number), 0) + 1).where(
            OutboxEventModel.aggregate_type == aggregate_type,
            OutboxEventModel.aggregate_id == aggregate_id,
        )
    )
    event = OutboxEventModel(
        id=uuid.uuid4(),
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        payload=payload,
        tenant_id=tenant_id,
        occurred_at=datetime.now(UTC),
        sequence_number=next_seq,
        relayed_at=None,
    )
    session.add(event)
    return event
