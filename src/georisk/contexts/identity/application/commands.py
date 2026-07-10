"""Command DTOs (Application Layer §1). Every state-changing action in
Identity is one of these — named as an imperative verb phrase, targeting
exactly one aggregate (``RegisterTenant`` is the one deliberate exception,
documented on its handler: it orchestrates two sequential single-aggregate
transactions, not one transaction touching two aggregates).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from georisk.contexts.identity.application.ports import AccessTokenClaims


@dataclass(frozen=True, slots=True)
class RegisterTenant:
    name: str
    tenant_email: str
    owner_email: str
    owner_password: str
    tenant_phone: str = ""
    tenant_address: str = ""
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class InviteUser:
    tenant_id: str
    email: str
    role_name: str
    invited_by: str
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class AcceptInvitation:
    invitation_token: str
    password: str


@dataclass(frozen=True, slots=True)
class ChangeUserRole:
    tenant_id: str
    user_id: str
    new_role_name: str
    changed_by: str


@dataclass(frozen=True, slots=True)
class SuspendUser:
    tenant_id: str
    user_id: str
    changed_by: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ReactivateUser:
    tenant_id: str
    user_id: str
    changed_by: str


@dataclass(frozen=True, slots=True)
class DeactivateUser:
    tenant_id: str
    user_id: str
    changed_by: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ChangePassword:
    tenant_id: str
    user_id: str
    current_password: str
    new_password: str


@dataclass(frozen=True, slots=True)
class Login:
    email: str
    password: str


@dataclass(frozen=True, slots=True)
class RefreshAccessToken:
    refresh_token: str


@dataclass(frozen=True, slots=True)
class Logout:
    refresh_token: str
    # Sprint D: populated only when the caller's request also carried a
    # (decodable, not-yet-expired) ``Authorization`` bearer header — logout
    # remains fully functional without one (backward compatible with every
    # pre-Sprint-D client that only ever sent ``refresh_token``), but when
    # present, that specific access token is revoked too, not just the
    # refresh token — see ``handlers_auth.py``'s ``LogoutHandler``.
    access_token_claims: AccessTokenClaims | None = None
    access_token_expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class RevokeAllSessions:
    """Self-service only — always acts on the calling, already-authenticated
    user (``current_user.id`` from the route), never on an arbitrary user
    ID an admin supplies, so there's no cross-tenant surface to check here
    unlike ``SuspendUser``/``DeactivateUser``."""

    user_id: str


@dataclass(frozen=True, slots=True)
class RequestPasswordReset:
    email: str
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class ResetPassword:
    reset_token: str
    new_password: str
