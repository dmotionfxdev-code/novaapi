"""FastAPI dependencies for authentication and authorization. Every
protected route depends on ``get_current_user`` (or, for endpoints that
only need coarse claims, ``get_current_claims``) plus, where relevant,
``require_permission(...)`` — this is the enforcement layer; the JWT
middleware (api/middleware/tenant_context.py) only sets logging/tracing
context and never itself authorizes anything (Implementation Bootstrap §3).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
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
from georisk.contexts.identity.infrastructure.repositories import (
    SqlAlchemyRevokedAccessTokenRepository,
    SqlAlchemyUserRepository,
)
from georisk.contexts.identity.infrastructure.security import (
    Argon2PasswordHasherAdapter,
    JwtAccessTokenIssuer,
    SecretsOpaqueTokenGenerator,
)
from georisk.db.session import Database, get_session
from georisk.settings import Settings, get_settings
from georisk.shared_kernel.errors import AuthenticationFailedError, AuthorizationDeniedError

_bearer_scheme = HTTPBearer(auto_error=True)
# Sprint D: logout must keep working for a caller that sends no
# ``Authorization`` header at all (pre-Sprint-D API contract, still
# covered by ``test_identity_api.py``'s idempotent-logout assertions) —
# ``auto_error=False`` makes the credentials optional instead of a hard
# 403 when absent.
_optional_bearer_scheme = HTTPBearer(auto_error=False)

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


async def get_optional_decoded_access_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer_scheme)],
    access_token_issuer: Annotated[AccessTokenIssuer, Depends(get_access_token_issuer)],
) -> tuple[AccessTokenClaims, datetime] | None:
    """Best-effort decode for logout only — a missing, malformed, or
    already-expired access token is not an error here (the refresh-token
    revocation half of logout must still proceed independently; see
    ``routes_auth.py``'s ``logout``), mirroring the same best-effort
    posture ``TenantContextMiddleware`` already uses for the same header.
    """
    if credentials is None:
        return None
    try:
        claims = access_token_issuer.decode(credentials.credentials)
        expires_at = access_token_issuer.decode_expiry(credentials.credentials)
    except Exception:  # noqa: BLE001 — best-effort only, see docstring above
        return None
    return claims, expires_at


async def get_current_claims(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
    access_token_issuer: Annotated[AccessTokenIssuer, Depends(get_access_token_issuer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AccessTokenClaims:
    """The single dependency every authenticated route sits on top of
    (directly via ``get_current_user``, or indirectly via
    ``require_permission``) — Sprint D added a genuine revocation check
    here so BOTH paths reject a revoked token identically, closing a real
    gap: ``require_permission`` previously trusted the JWT's embedded
    claims alone and never re-checked the database at all, so a suspended/
    deactivated user — or an explicitly revoked session — stayed fully
    authorized on any permission-only route until their access token's
    natural 8h expiry. That staleness was an accepted tradeoff for
    *permissions* (a role change taking up to 8h to propagate); it was
    never an accepted tradeoff for *revocation*, which this closes
    unconditionally, at the cost of one extra user lookup per request that
    ``get_current_user`` would already be paying — cached below on
    ``request.state`` so it doesn't pay it twice in the same request.
    """
    claims = access_token_issuer.decode(credentials.credentials)

    revoked_repo = SqlAlchemyRevokedAccessTokenRepository(session)
    if claims.jti and await revoked_repo.is_revoked(claims.jti):
        raise AuthenticationFailedError("This session has been logged out")

    user_repo = SqlAlchemyUserRepository(session)
    user = await user_repo.get_by_id(claims.user_id)
    if user is None:
        raise UserNotFoundError(f"User {claims.user_id} not found")
    if not user.is_login_eligible():
        raise UserNotActiveError("This account is no longer active")
    if user.token_generation != claims.token_generation:
        raise AuthenticationFailedError(
            "This session has been revoked — please log in again"
        )

    request.state.current_user = user
    return claims


async def get_current_user(
    request: Request,
    claims: Annotated[AccessTokenClaims, Depends(get_current_claims)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Returns the same ``User`` row ``get_current_claims`` already fetched
    for its revocation/active-status check (cached on ``request.state`` —
    same request, same session, no staleness risk) instead of querying
    twice.
    """
    cached = getattr(request.state, "current_user", None)
    if cached is not None:
        return cached

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
