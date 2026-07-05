"""Authentication command handlers: login, refresh-token rotation (with
reuse detection), logout, and the password-reset request/confirm pair.

Security note threaded through this file: ``RequestPasswordReset``'s raw
token is deliberately NEVER returned through the HTTP response — the
caller of that endpoint may be the account owner, or may be an attacker
probing an email address; either way, echoing the token back in the
response would let whoever made the request immediately complete the
reset, defeating the entire point of a side-channel (email) delivery step.
Real delivery is Notification's job (Roadmap Sprint 10); until then, the
token is discoverable only via direct repository/DB access — appropriate
for this sprint's internal testing, wrong for anything exposed over HTTP.
``InviteUser`` (handlers_user.py) is the deliberate opposite: the caller
there is an authenticated admin inviting someone *else*, so returning the
raw invitation link to them (to forward out-of-band) is the intended,
safe behavior given no notification pipeline exists yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.application.commands import (
    Login,
    Logout,
    RefreshAccessToken,
    RequestPasswordReset,
    ResetPassword,
)
from georisk.contexts.identity.application.ports import (
    AccessTokenClaims,
    AccessTokenIssuer,
    IssuedAccessToken,
    OpaqueTokenGenerator,
    PasswordHasher,
)
from georisk.contexts.identity.application.services import PasswordPolicy
from georisk.contexts.identity.domain.entities import User
from georisk.contexts.identity.domain.errors import (
    InvalidCredentialsError,
    InvalidOrExpiredTokenError,
    RefreshTokenReuseDetectedError,
    UserNotActiveError,
    UserNotFoundError,
)
from georisk.contexts.identity.domain.events import (
    PasswordResetCompleted,
    PasswordResetRequested,
    RefreshTokenIssued,
    RefreshTokenReuseDetected,
    RefreshTokenRevoked,
    RefreshTokenRotated,
    UserLoggedIn,
    UserLoginFailed,
)
from georisk.contexts.identity.domain.tokens import PasswordResetToken, RefreshToken
from georisk.contexts.identity.infrastructure.repositories import (
    SqlAlchemyPasswordResetTokenRepository,
    SqlAlchemyRefreshTokenRepository,
    SqlAlchemyUserRepository,
)
from georisk.db.outbox_writer import append_event


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    user: User
    raw_refresh_token: str
    access_token: IssuedAccessToken


def _claims_for(user: User) -> AccessTokenClaims:
    return AccessTokenClaims(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role_name=user.role.name,
        permissions=user.role.permissions,
    )


class LoginHandler:
    def __init__(
        self,
        session: AsyncSession,
        password_hasher: PasswordHasher,
        token_generator: OpaqueTokenGenerator,
        access_token_issuer: AccessTokenIssuer,
    ) -> None:
        self._session = session
        self._password_hasher = password_hasher
        self._token_generator = token_generator
        self._access_token_issuer = access_token_issuer

    async def handle(self, command: Login) -> AuthenticatedSession:
        user_repo = SqlAlchemyUserRepository(self._session)
        user = await user_repo.get_by_email(command.email)

        if user is None:
            await self._record_failure(command.email, reason="user_not_found")
            raise InvalidCredentialsError("Invalid email or password")

        if not user.is_login_eligible():
            await self._record_failure(command.email, reason=f"status_{user.status.value.lower()}")
            raise UserNotActiveError("This account is not active")

        if user.hashed_password is None or not self._password_hasher.verify(
            command.password, user.hashed_password
        ):
            await self._record_failure(command.email, reason="wrong_password")
            raise InvalidCredentialsError("Invalid email or password")

        user.record_login()
        await user_repo.save(user, expected_version=user.version)

        refresh_repo = SqlAlchemyRefreshTokenRepository(self._session)
        raw_refresh = self._token_generator.generate()
        refresh_token = RefreshToken.issue(
            user_id=user.id,
            tenant_id=user.tenant_id,
            token_hash=self._token_generator.hash_token(raw_refresh),
        )
        await refresh_repo.save(refresh_token)

        access_token = self._access_token_issuer.issue(_claims_for(user))

        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=UserLoggedIn.event_type,
            payload=UserLoggedIn(user_id=str(user.id), tenant_id=str(user.tenant_id)).payload(),
            tenant_id=user.tenant_id.value,
        )
        await append_event(
            self._session,
            aggregate_type="RefreshToken",
            aggregate_id=str(refresh_token.id),
            event_type=RefreshTokenIssued.event_type,
            payload=RefreshTokenIssued(
                user_id=str(user.id),
                tenant_id=str(user.tenant_id),
                refresh_token_id=str(refresh_token.id),
            ).payload(),
            tenant_id=user.tenant_id.value,
        )
        await self._session.commit()
        return AuthenticatedSession(
            user=user, raw_refresh_token=raw_refresh, access_token=access_token
        )

    async def _record_failure(self, email: str, *, reason: str) -> None:
        await append_event(
            self._session,
            aggregate_type="LoginAttempt",
            aggregate_id=email,
            event_type=UserLoginFailed.event_type,
            payload=UserLoginFailed(email=email, reason=reason).payload(),
            tenant_id=None,
        )
        await self._session.commit()


@dataclass(frozen=True, slots=True)
class RefreshedSession:
    raw_refresh_token: str
    access_token: IssuedAccessToken


class RefreshAccessTokenHandler:
    def __init__(
        self,
        session: AsyncSession,
        token_generator: OpaqueTokenGenerator,
        access_token_issuer: AccessTokenIssuer,
    ) -> None:
        self._session = session
        self._token_generator = token_generator
        self._access_token_issuer = access_token_issuer

    async def handle(self, command: RefreshAccessToken) -> RefreshedSession:
        refresh_repo = SqlAlchemyRefreshTokenRepository(self._session)
        user_repo = SqlAlchemyUserRepository(self._session)

        token_hash = self._token_generator.hash_token(command.refresh_token)
        token = await refresh_repo.get_by_token_hash(token_hash)
        if token is None:
            raise InvalidOrExpiredTokenError("Refresh token not found")

        if token.revoked_at is not None:
            # A revoked (already-rotated) token was presented again — the
            # standard rotation-with-reuse-detection signal of token theft.
            # Response: nuke every active session for this user.
            await refresh_repo.revoke_all_active_for_user(
                token.user_id, reason="refresh token reuse detected"
            )
            await append_event(
                self._session,
                aggregate_type="RefreshToken",
                aggregate_id=str(token.id),
                event_type=RefreshTokenReuseDetected.event_type,
                payload=RefreshTokenReuseDetected(
                    user_id=str(token.user_id),
                    tenant_id=str(token.tenant_id),
                    refresh_token_id=str(token.id),
                ).payload(),
                tenant_id=token.tenant_id.value,
            )
            await self._session.commit()
            raise RefreshTokenReuseDetectedError(
                "This refresh token has already been used — "
                "all sessions for this account have been revoked"
            )

        token.assert_active()

        user = await user_repo.get_by_id(token.user_id)
        if user is None or not user.is_login_eligible():
            raise UserNotActiveError("This account is not active")

        new_raw_refresh = self._token_generator.generate()
        new_token = RefreshToken.issue(
            user_id=token.user_id,
            tenant_id=token.tenant_id,
            token_hash=self._token_generator.hash_token(new_raw_refresh),
        )
        token.revoke(replaced_by_id=new_token.id)

        # Save the NEW token first — the old token's row update sets
        # replaced_by_id to point at it, which violates the foreign key
        # constraint if that row doesn't exist in the database yet. Caught
        # by actually running this against real Postgres during Sprint 1
        # validation (a plain unit/mock test would never have exercised
        # the FK constraint at all).
        await refresh_repo.save(new_token)
        await refresh_repo.save(token)

        access_token = self._access_token_issuer.issue(_claims_for(user))

        await append_event(
            self._session,
            aggregate_type="RefreshToken",
            aggregate_id=str(new_token.id),
            event_type=RefreshTokenRotated.event_type,
            payload=RefreshTokenRotated(
                user_id=str(user.id),
                tenant_id=str(user.tenant_id),
                old_refresh_token_id=str(token.id),
                new_refresh_token_id=str(new_token.id),
            ).payload(),
            tenant_id=user.tenant_id.value,
        )
        await self._session.commit()
        return RefreshedSession(raw_refresh_token=new_raw_refresh, access_token=access_token)


class LogoutHandler:
    def __init__(self, session: AsyncSession, token_generator: OpaqueTokenGenerator) -> None:
        self._session = session
        self._token_generator = token_generator

    async def handle(self, command: Logout) -> None:
        refresh_repo = SqlAlchemyRefreshTokenRepository(self._session)
        token_hash = self._token_generator.hash_token(command.refresh_token)
        token = await refresh_repo.get_by_token_hash(token_hash)

        if token is None or token.revoked_at is not None:
            return  # Already logged out — idempotent no-op, not an error.

        token.revoke()
        await refresh_repo.save(token)
        await append_event(
            self._session,
            aggregate_type="RefreshToken",
            aggregate_id=str(token.id),
            event_type=RefreshTokenRevoked.event_type,
            payload=RefreshTokenRevoked(
                user_id=str(token.user_id),
                tenant_id=str(token.tenant_id),
                refresh_token_id=str(token.id),
                reason="logout",
            ).payload(),
            tenant_id=token.tenant_id.value,
        )
        await self._session.commit()


class RequestPasswordResetHandler:
    def __init__(self, session: AsyncSession, token_generator: OpaqueTokenGenerator) -> None:
        self._session = session
        self._token_generator = token_generator

    async def handle(self, command: RequestPasswordReset) -> None:
        """Always returns ``None`` regardless of whether the email exists —
        callers must not be able to distinguish "email sent" from "no such
        account" (email enumeration hardening)."""
        user_repo = SqlAlchemyUserRepository(self._session)
        user = await user_repo.get_by_email(command.email)
        if user is None:
            return

        reset_repo = SqlAlchemyPasswordResetTokenRepository(self._session)
        raw_token = self._token_generator.generate()
        reset_token = PasswordResetToken.issue(
            user_id=user.id,
            tenant_id=user.tenant_id,
            token_hash=self._token_generator.hash_token(raw_token),
        )
        await reset_repo.save(reset_token)
        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=PasswordResetRequested.event_type,
            payload=PasswordResetRequested(
                user_id=str(user.id), tenant_id=str(user.tenant_id)
            ).payload(),
            tenant_id=user.tenant_id.value,
        )
        await self._session.commit()
        # raw_token is intentionally discarded here (not returned) — see
        # module docstring. Real delivery lands with Notification (Sprint 10).


class ResetPasswordHandler:
    def __init__(
        self,
        session: AsyncSession,
        password_hasher: PasswordHasher,
        token_generator: OpaqueTokenGenerator,
    ) -> None:
        self._session = session
        self._password_hasher = password_hasher
        self._token_generator = token_generator

    async def handle(self, command: ResetPassword) -> User:
        PasswordPolicy.validate(command.new_password)

        reset_repo = SqlAlchemyPasswordResetTokenRepository(self._session)
        user_repo = SqlAlchemyUserRepository(self._session)

        token_hash = self._token_generator.hash_token(command.reset_token)
        reset_token = await reset_repo.get_by_token_hash(token_hash)
        if reset_token is None:
            raise InvalidOrExpiredTokenError("Password reset token not found")
        reset_token.assert_valid()

        user = await user_repo.get_by_id(reset_token.user_id)
        if user is None:
            raise UserNotFoundError(f"User {reset_token.user_id} not found")

        user.set_password(self._password_hasher.hash(command.new_password))
        await user_repo.save(user, expected_version=user.version)

        reset_token.mark_used()
        await reset_repo.save(reset_token)

        refresh_repo = SqlAlchemyRefreshTokenRepository(self._session)
        await refresh_repo.revoke_all_active_for_user(user.id, reason="password reset")

        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=PasswordResetCompleted.event_type,
            payload=PasswordResetCompleted(
                user_id=str(user.id), tenant_id=str(user.tenant_id)
            ).payload(),
            tenant_id=user.tenant_id.value,
        )
        await self._session.commit()
        return user
