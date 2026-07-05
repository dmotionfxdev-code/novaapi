"""Authentication routes — all public except logout/password-change, which
require a valid session. Every mutating route here is a thin adapter: parse
request -> build a command -> invoke the one handler that owns it -> map
the result to a response schema. No business logic lives in this file.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.application.commands import (
    Login,
    Logout,
    RefreshAccessToken,
    RequestPasswordReset,
    ResetPassword,
)
from georisk.contexts.identity.application.handlers_auth import (
    LoginHandler,
    LogoutHandler,
    RefreshAccessTokenHandler,
    RequestPasswordResetHandler,
    ResetPasswordHandler,
)
from georisk.contexts.identity.application.ports import (
    AccessTokenIssuer,
    OpaqueTokenGenerator,
    PasswordHasher,
)
from georisk.contexts.identity.interface.dependencies import (
    get_access_token_issuer,
    get_password_hasher,
    get_token_generator,
)
from georisk.contexts.identity.interface.schemas import (
    LoginRequest,
    LogoutRequest,
    RefreshTokenRequest,
    RequestPasswordResetRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from georisk.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    password_hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    token_generator: Annotated[OpaqueTokenGenerator, Depends(get_token_generator)],
    access_token_issuer: Annotated[AccessTokenIssuer, Depends(get_access_token_issuer)],
) -> TokenResponse:
    handler = LoginHandler(session, password_hasher, token_generator, access_token_issuer)
    result = await handler.handle(Login(email=body.email, password=body.password))
    return TokenResponse(
        access_token=result.access_token.token,
        refresh_token=result.raw_refresh_token,
        expires_in=result.access_token.expires_in_seconds,
    )


@router.post("/token/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshTokenRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    token_generator: Annotated[OpaqueTokenGenerator, Depends(get_token_generator)],
    access_token_issuer: Annotated[AccessTokenIssuer, Depends(get_access_token_issuer)],
) -> TokenResponse:
    handler = RefreshAccessTokenHandler(session, token_generator, access_token_issuer)
    result = await handler.handle(RefreshAccessToken(refresh_token=body.refresh_token))
    return TokenResponse(
        access_token=result.access_token.token,
        refresh_token=result.raw_refresh_token,
        expires_in=result.access_token.expires_in_seconds,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    token_generator: Annotated[OpaqueTokenGenerator, Depends(get_token_generator)],
) -> Response:
    handler = LogoutHandler(session, token_generator)
    await handler.handle(Logout(refresh_token=body.refresh_token))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    body: RequestPasswordResetRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    token_generator: Annotated[OpaqueTokenGenerator, Depends(get_token_generator)],
) -> dict[str, str]:
    handler = RequestPasswordResetHandler(session, token_generator)
    await handler.handle(RequestPasswordReset(email=body.email))
    # Identical response whether or not the email exists — see
    # handlers_auth.py's module docstring on email-enumeration hardening.
    return {"detail": "If that email is registered, a password reset link has been sent."}


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    body: ResetPasswordRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    password_hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    token_generator: Annotated[OpaqueTokenGenerator, Depends(get_token_generator)],
) -> Response:
    handler = ResetPasswordHandler(session, password_hasher, token_generator)
    await handler.handle(
        ResetPassword(reset_token=body.reset_token, new_password=body.new_password)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
