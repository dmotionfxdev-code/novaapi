"""Idempotency check-before-execute helper (Application Layer §2 pipeline
step 3, §11). A command handler that supports idempotency calls
``get_cached`` before doing any work; if it returns a result, the handler
returns that cached result verbatim instead of re-executing. On success,
the handler calls ``store`` with the outcome before its transaction
commits, so the record and the effect it describes are atomic.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.db.idempotency_models import IdempotencyKeyModel


@dataclass(frozen=True, slots=True)
class CachedResult:
    response_body: dict
    status_code: int


async def get_cached(
    session: AsyncSession, *, idempotency_key: str, command_type: str
) -> CachedResult | None:
    result = await session.execute(
        select(IdempotencyKeyModel).where(
            IdempotencyKeyModel.idempotency_key == idempotency_key,
            IdempotencyKeyModel.command_type == command_type,
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        return None
    return CachedResult(response_body=model.response_body, status_code=model.status_code)


async def store(
    session: AsyncSession,
    *,
    idempotency_key: str,
    command_type: str,
    response_body: dict,
    status_code: int,
) -> None:
    session.add(
        IdempotencyKeyModel(
            id=uuid.uuid4(),
            idempotency_key=idempotency_key,
            command_type=command_type,
            response_body=response_body,
            status_code=status_code,
            created_at=datetime.now(UTC),
        )
    )
