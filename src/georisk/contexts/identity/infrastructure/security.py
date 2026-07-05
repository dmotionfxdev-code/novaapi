"""Concrete implementations of the ports declared in
``contexts/identity/application/ports.py``. This is the only module in the
Identity context allowed to import ``argon2``, ``jwt``, or ``secrets`` for
token generation — domain and application code depend on the port
interfaces, never on these classes directly (dependency inversion).
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid

import jwt
from argon2 import PasswordHasher as _Argon2PasswordHasher
from argon2.exceptions import VerifyMismatchError

from georisk.contexts.identity.application.ports import AccessTokenClaims, IssuedAccessToken
from georisk.contexts.identity.domain.value_objects import (
    PermissionCode,
    RoleName,
    TenantId,
    UserId,
)
from georisk.shared_kernel.errors import AuthenticationFailedError


class Argon2PasswordHasherAdapter:
    """Argon2id — OWASP's current top recommendation for password hashing."""

    def __init__(self) -> None:
        self._hasher = _Argon2PasswordHasher()

    def hash(self, plaintext: str) -> str:
        return self._hasher.hash(plaintext)

    def verify(self, plaintext: str, hashed: str) -> bool:
        try:
            return self._hasher.verify(hashed, plaintext)
        except VerifyMismatchError:
            return False


class SecretsOpaqueTokenGenerator:
    """Raw tokens are high-entropy URL-safe random strings (refresh /
    password-reset / invitation tokens) — never a JWT, never reversible.
    Only a SHA-256 hash of the raw value is ever persisted (tokens.py's
    docstring), so a database compromise alone cannot reconstruct a usable
    token.
    """

    def generate(self) -> str:
        return secrets.token_urlsafe(32)

    def hash_token(self, raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class JwtAccessTokenIssuer:
    def __init__(self, *, secret_key: str, algorithm: str, ttl_seconds: int) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._ttl_seconds = ttl_seconds

    def issue(self, claims: AccessTokenClaims) -> IssuedAccessToken:
        now = int(time.time())
        payload = {
            "sub": str(claims.user_id),
            "tenant_id": str(claims.tenant_id),
            "role": claims.role_name.value,
            "permissions": sorted(p.value for p in claims.permissions),
            "type": "access",
            "iat": now,
            "exp": now + self._ttl_seconds,
            "jti": str(uuid.uuid4()),
        }
        token = jwt.encode(payload, self._secret_key, algorithm=self._algorithm)
        return IssuedAccessToken(token=token, expires_in_seconds=self._ttl_seconds)

    def decode(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationFailedError("Access token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthenticationFailedError("Access token is invalid") from exc

        if payload.get("type") != "access":
            raise AuthenticationFailedError("Token is not an access token")

        try:
            return AccessTokenClaims(
                user_id=UserId.from_string(payload["sub"]),
                tenant_id=TenantId.from_string(payload["tenant_id"]),
                role_name=RoleName(payload["role"]),
                permissions=frozenset(PermissionCode(p) for p in payload.get("permissions", [])),
            )
        except (KeyError, ValueError) as exc:
            raise AuthenticationFailedError("Access token payload is malformed") from exc
