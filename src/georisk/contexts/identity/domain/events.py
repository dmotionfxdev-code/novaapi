"""Identity domain events — the catalog this context contributes to the
platform's overall event catalog (Domain Model §5). Emitted by command
handlers into the outbox (``db/outbox_writer.py``) within the same
transaction as the aggregate change that caused them; this is what
satisfies Sprint 1's "Audit Events" requirement — a durable, queryable
record of every significant identity action, with no separate audit
mechanism to build or keep in sync.

Every event is a frozen dataclass with a class-level ``event_type`` and a
``payload()`` method producing the dict written to the outbox row.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class TenantRegistered:
    event_type: ClassVar[str] = "identity.TenantRegistered"
    tenant_id: str
    name: str
    slug: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class UserRegistered:
    event_type: ClassVar[str] = "identity.UserRegistered"
    user_id: str
    tenant_id: str
    email: str
    role_name: str
    status: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class UserInvited:
    event_type: ClassVar[str] = "identity.UserInvited"
    user_id: str
    tenant_id: str
    email: str
    role_name: str
    invited_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class UserActivated:
    event_type: ClassVar[str] = "identity.UserActivated"
    user_id: str
    tenant_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class UserLoggedIn:
    event_type: ClassVar[str] = "identity.UserLoggedIn"
    user_id: str
    tenant_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class UserLoginFailed:
    event_type: ClassVar[str] = "identity.UserLoginFailed"
    email: str
    reason: str
    # No tenant_id / user_id — a failed login for an unknown email must not
    # leak whether that email exists (errors.py's InvalidCredentialsError
    # note); the event itself follows the same discipline.

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class UserLoggedOut:
    event_type: ClassVar[str] = "identity.UserLoggedOut"
    user_id: str
    tenant_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class UserRoleChanged:
    event_type: ClassVar[str] = "identity.UserRoleChanged"
    user_id: str
    tenant_id: str
    old_role_name: str
    new_role_name: str
    changed_by: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class UserStatusChanged:
    event_type: ClassVar[str] = "identity.UserStatusChanged"
    user_id: str
    tenant_id: str
    old_status: str
    new_status: str
    changed_by: str
    reason: str = ""

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class PasswordChanged:
    event_type: ClassVar[str] = "identity.PasswordChanged"
    user_id: str
    tenant_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class PasswordResetRequested:
    event_type: ClassVar[str] = "identity.PasswordResetRequested"
    user_id: str
    tenant_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class PasswordResetCompleted:
    event_type: ClassVar[str] = "identity.PasswordResetCompleted"
    user_id: str
    tenant_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class RefreshTokenIssued:
    event_type: ClassVar[str] = "identity.RefreshTokenIssued"
    user_id: str
    tenant_id: str
    refresh_token_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class RefreshTokenRotated:
    event_type: ClassVar[str] = "identity.RefreshTokenRotated"
    user_id: str
    tenant_id: str
    old_refresh_token_id: str
    new_refresh_token_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class RefreshTokenReuseDetected:
    event_type: ClassVar[str] = "identity.RefreshTokenReuseDetected"
    user_id: str
    tenant_id: str
    refresh_token_id: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}


@dataclass(frozen=True, slots=True)
class RefreshTokenRevoked:
    event_type: ClassVar[str] = "identity.RefreshTokenRevoked"
    user_id: str
    tenant_id: str
    refresh_token_id: str
    reason: str

    def payload(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "event_type"}
