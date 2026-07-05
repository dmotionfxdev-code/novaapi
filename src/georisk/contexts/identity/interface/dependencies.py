"""FastAPI dependencies for authentication and authorization. Every
protected route depends on ``get_current_user`` (or, for endpoints that
only need coarse claims, ``get_current_claims``) plus, where relevant,
``require_permission(...)`` — this is the enforcement layer; the JWT
middleware (api/middleware/tenant_context.py) only sets logging/tracing
context and never itself authorizes anything (Implementation Bootstrap §3).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.application.ports import (
    AccessTokenClaims,
    AccessTokenIssuer,
    OpaqueTokenGenerator,
    PasswordHasher,
)
from georisk.contexts.identity.domain.entities import User
from georisk.contexts.identity.domain.errors import UserNotActiveError, UserNotFoundError
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.infrastructure.repositories import SqlAlchemyUserRepository
from georisk.contexts.identity.infrastructure.security import (
    Argon2PasswordHasherAdapter,
    JwtAccessTokenIssuer,
    SecretsOpaqueTokenGenerator,
)
from georisk.db.session import Database, get_session
from georisk.settings import Settings, get_settings
from georisk.shared_kernel.errors import AuthorizationDeniedError

_bearer_scheme = HTTPBearer(auto_error=True)

# Stateless, cheap to construct — no need to cache beyond module import.
_password_hasher = Argon2PasswordHasherAdapter()
_token_generator = SecretsOpaqueTokenGenerator()


def get_password_hasher() -> PasswordHasher:
    return _password_hasher


def get_token_generator() -> OpaqueTokenGenerator:
    return _token_generator


def get_access_token_issuer(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AccessTokenIssuer:
    return JwtAccessTokenIssuer(
        secret_key=settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
        ttl_seconds=settings.jwt_access_token_ttl_seconds,
    )


def get_database(request: Request) -> Database:
    """For the one handler (RegisterTenantHandler) that needs to open more
    than one transaction — see its module docstring for why.
    """
    return request.app.state.db


async def get_current_claims(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    access_token_issuer: Annotated[AccessTokenIssuer, Depends(get_access_token_issuer)],
) -> AccessTokenClaims:
    return access_token_issuer.decode(credentials.credentials)


async def get_current_user(
    claims: Annotated[AccessTokenClaims, Depends(get_current_claims)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Re-reads the user from the database on every request rather than
    trusting the JWT's identity claim alone — a status change (suspended,
    deactivated) since token issuance must take effect immediately for
    authentication, even though the *permission* claims embedded in the
    token itself are allowed to be up to 8h stale (module docstring
    tradeoff noted in application/ports.py).
    """
    user_repo = SqlAlchemyUserRepository(session)
    user = await user_repo.get_by_id(claims.user_id)
    if user is None:
        raise UserNotFoundError(f"User {claims.user_id} not found")
    if not user.is_login_eligible():
        raise UserNotActiveError("This account is no longer active")
    return user


def require_permission(code: PermissionCode) -> Callable[..., Awaitable[AccessTokenClaims]]:
    """Dependency factory — checks the *token's* embedded permission claims,
    not a fresh DB lookup, trading up-to-the-second accuracy for avoiding a
    query on every authorized request. Acceptable given the 8h access-token
    lifetime; a role change takes effect on that user's next token refresh.
    """

    async def _check(
        claims: Annotated[AccessTokenClaims, Depends(get_current_claims)],
    ) -> AccessTokenClaims:
        if code not in claims.permissions:
            raise AuthorizationDeniedError(f"This action requires the {code.value!r} permission")
        return claims

    return _check
