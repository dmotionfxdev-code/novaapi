"""Ports the application layer depends on but does not implement —
dependency inversion (Architecture Redesign §9). Concrete implementations
live in ``contexts/identity/infrastructure`` (argon2, PyJWT, ``secrets``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from georisk.contexts.identity.domain.value_objects import (
    PermissionCode,
    RoleName,
    TenantId,
    UserId,
)


class PasswordHasher(Protocol):
    def hash(self, plaintext: str) -> str: ...
    def verify(self, plaintext: str, hashed: str) -> bool: ...


class OpaqueTokenGenerator(Protocol):
    """Generates the raw, high-entropy token string handed to a client
    (refresh tokens, password-reset tokens, invitation tokens) and hashes
    one for storage/lookup — the raw value is never persisted.
    """

    def generate(self) -> str: ...
    def hash_token(self, raw_token: str) -> str: ...


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: UserId
    tenant_id: TenantId
    role_name: RoleName
    permissions: frozenset[PermissionCode]
    # Sprint D: ``token_generation`` is a real claim on both sides —
    # ``AccessTokenIssuer.issue()`` embeds the issuing user's *current*
    # ``User.token_generation`` value, and ``.decode()`` extracts it back
    # out of the JWT, so ``get_current_claims`` (interface/dependencies.py)
    # can compare it against a fresh read of the user's counter to detect
    # bulk revocation (password reset/suspend/deactivate/"revoke all
    # sessions"). ``jti`` is decode-only in practice — the issuer always
    # generates a fresh one internally rather than reading it off the
    # claims object it's given — but lives on this same dataclass so
    # ``get_current_claims`` and the logout handler (which needs to know
    # the *current* request's jti to revoke it) both work off one shape.
    # Both default so the many call sites that only care about identity/
    # permissions (e.g. every existing test) are unaffected.
    token_generation: int = 0
    jti: str = ""


@dataclass(frozen=True, slots=True)
class IssuedAccessToken:
    token: str
    expires_in_seconds: int


class AccessTokenIssuer(Protocol):
    def issue(self, claims: AccessTokenClaims) -> IssuedAccessToken: ...

    def decode(self, token: str) -> AccessTokenClaims:
        """Raises ``georisk.shared_kernel.errors.AuthenticationFailedError``
        (or a subclass) on an invalid, expired, or malformed token — 401,
        not 403, since a bad token means no identity was ever established."""
        ...

    def decode_expiry(self, token: str) -> datetime:
        """Returns the token's expiry regardless of whether it has already
        passed (Sprint D) — used only to populate ``RevokedAccessToken.
        expires_at`` bookkeeping when logout revokes the caller's current
        access token."""
        ...
