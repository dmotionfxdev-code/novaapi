"""Generic typed-identifier mechanism.

Domain Model §3: every cross-aggregate reference uses a typed ID value
object (``AssessmentId``, ``TenantId``, ...) rather than a bare ``str``/
``UUID``, so a ``StageResultId`` can never be accidentally passed where an
``AoiId`` is expected. This module provides only the generic base every
concrete typed ID subclasses — no concrete ID types are defined here.
Concrete IDs (``TenantId``, ``AssessmentId``, ...) are defined inside the
bounded context that owns the aggregate they identify, starting with
``contexts/identity`` in Roadmap Sprint 1.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Self


@dataclass(frozen=True, slots=True)
class TypedId:
    """Immutable wrapper around a UUID4 value.

    Subclass per aggregate root, e.g.::

        class TenantId(TypedId):
            pass

    Two different ``TypedId`` subclasses holding the same underlying UUID
    are never equal to each other — equality and hashing are scoped to the
    concrete subclass, not the raw value, which is what makes the "never
    pass the wrong kind of ID" guarantee real rather than cosmetic.
    """

    value: uuid.UUID

    @classmethod
    def new(cls) -> Self:
        # `Self`, not `TypedId` — Domain Model §3's entire point is that
        # `TenantId` and `UserId` must never be interchangeable. Returning
        # the base type here would defeat that at every call site: mypy
        # could no longer catch `SomeOtherId.new()` being passed where a
        # `TenantId` was expected, because everything would type-check as
        # the base class instead of the concrete subclass actually
        # constructed. Caught during Sprint 1 validation — this is a
        # correction, not the original draft.
        return cls(value=uuid.uuid4())

    @classmethod
    def from_string(cls, raw: str) -> Self:
        return cls(value=uuid.UUID(raw))

    def __str__(self) -> str:
        return str(self.value)

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self.value == other.value  # type: ignore[attr-defined]

    def __hash__(self) -> int:
        return hash((type(self), self.value))
