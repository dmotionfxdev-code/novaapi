"""Ports the application layer depends on but does not implement —
dependency inversion (Architecture Redesign §9). Concrete implementations
live in ``contexts/identity/infrastructure`` (argon2, PyJWT, ``secrets``).
"""

from __future__ import annotations

from dataclasses import dataclass
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
