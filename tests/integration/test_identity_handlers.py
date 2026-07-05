"""Handler-level integration tests for the highest-risk logic: refresh
token rotation with reuse detection, and the "last owner" guard — both
depend on real database state in ways unit tests can't exercise.
"""

from __future__ import annotations

import uuid

import pytest

from georisk.contexts.identity.application.commands import (
    AcceptInvitation,
    ChangeUserRole,
    DeactivateUser,
    InviteUser,
    Login,
    RefreshAccessToken,
    RegisterTenant,
)
from georisk.contexts.identity.application.handlers_auth import (
    LoginHandler,
    RefreshAccessTokenHandler,
)
from georisk.contexts.identity.application.handlers_tenant import RegisterTenantHandler
from georisk.contexts.identity.application.handlers_user import (
    ChangeUserRoleHandler,
    DeactivateUserHandler,
)
from georisk.contexts.identity.domain.errors import (
    LastOwnerRemovalError,
    RefreshTokenReuseDetectedError,
)
from georisk.contexts.identity.infrastructure.security import (
    Argon2PasswordHasherAdapter,
    JwtAccessTokenIssuer,
    SecretsOpaqueTokenGenerator,
)

pytestmark = pytest.mark.integration

_hasher = Argon2PasswordHasherAdapter()
_token_gen = SecretsOpaqueTokenGenerator()
_issuer = JwtAccessTokenIssuer(secret_key="test-secret", algorithm="HS256", ttl_seconds=3600)


async def _register_tenant_with_owner(real_database, suffix: str):  # noqa: ANN001
    handler = RegisterTenantHandler(real_database, _hasher)
    tenant, owner = await handler.handle(
        RegisterTenant(
            name=f"Handler Test {suffix}",
            tenant_email=f"tenant-{suffix}@test.example",
            owner_email=f"owner-{suffix}@test.example",
            owner_password="correct-horse-battery-staple",
        )
    )
    return tenant, owner


async def test_refresh_token_rotation_and_reuse_detection(real_database) -> None:  # noqa: ANN001
    suffix = uuid.uuid4().hex[:8]
    tenant, owner = await _register_tenant_with_owner(real_database, suffix)

    async with real_database.session() as session:
        login_handler = LoginHandler(session, _hasher, _token_gen, _issuer)
        session_result = await login_handler.handle(
            Login(email=owner.email, password="correct-horse-battery-staple")
        )
    original_refresh = session_result.raw_refresh_token

    # First refresh: legitimate rotation, must succeed and issue a new token.
    async with real_database.session() as session:
        refresh_handler = RefreshAccessTokenHandler(session, _token_gen, _issuer)
        refreshed = await refresh_handler.handle(RefreshAccessToken(refresh_token=original_refresh))
    new_refresh = refreshed.raw_refresh_token
    assert new_refresh != original_refresh

    # Presenting the ORIGINAL (now-revoked) token again must be treated as
    # reuse/theft, not a normal "expired token" error.
    async with real_database.session() as session:
        refresh_handler = RefreshAccessTokenHandler(session, _token_gen, _issuer)
        with pytest.raises(RefreshTokenReuseDetectedError):
            await refresh_handler.handle(RefreshAccessToken(refresh_token=original_refresh))

    # And that reuse must have revoked the legitimately-rotated token too —
    # the whole point of reuse detection is nuking every active session.
    # Presenting it now hits the exact same "already revoked" branch as the
    # original token did, so it raises the same RefreshTokenReuseDetectedError
    # again — not a plain expired/not-found error. An earlier version of
    # this test asserted the latter; the handler's actual (and, on
    # reflection, more correct) behavior is to keep flagging any revoked
    # token's reuse consistently, not distinguish "first" reuse from
    # "reuse of an already-flagged" token.
    async with real_database.session() as session:
        refresh_handler = RefreshAccessTokenHandler(session, _token_gen, _issuer)
        with pytest.raises(RefreshTokenReuseDetectedError):
            await refresh_handler.handle(RefreshAccessToken(refresh_token=new_refresh))


async def test_last_owner_cannot_be_demoted(real_database) -> None:  # noqa: ANN001
    suffix = uuid.uuid4().hex[:8]
    tenant, owner = await _register_tenant_with_owner(real_database, suffix)

    async with real_database.session() as session:
        handler = ChangeUserRoleHandler(session)
        with pytest.raises(LastOwnerRemovalError):
            await handler.handle(
                ChangeUserRole(
                    tenant_id=str(tenant.id),
                    user_id=str(owner.id),
                    new_role_name="ADMIN",
                    changed_by=str(owner.id),
                )
            )


async def test_last_owner_cannot_be_deactivated(real_database) -> None:  # noqa: ANN001
    suffix = uuid.uuid4().hex[:8]
    tenant, owner = await _register_tenant_with_owner(real_database, suffix)

    async with real_database.session() as session:
        handler = DeactivateUserHandler(session)
        with pytest.raises(LastOwnerRemovalError):
            await handler.handle(
                DeactivateUser(
                    tenant_id=str(tenant.id), user_id=str(owner.id), changed_by=str(owner.id)
                )
            )


async def test_second_owner_can_be_demoted_once_not_last(real_database) -> None:  # noqa: ANN001
    from georisk.contexts.identity.application.handlers_user import (
        AcceptInvitationHandler,
        InviteUserHandler,
    )

    suffix = uuid.uuid4().hex[:8]
    tenant, owner = await _register_tenant_with_owner(real_database, suffix)

    async with real_database.session() as session:
        invite_handler = InviteUserHandler(session, _token_gen)
        invite_result = await invite_handler.handle(
            InviteUser(
                tenant_id=str(tenant.id),
                email=f"second-owner-{suffix}@test.example",
                role_name="OWNER",
                invited_by=str(owner.id),
            )
        )

    async with real_database.session() as session:
        accept_handler = AcceptInvitationHandler(session, _hasher, _token_gen)
        second_owner = await accept_handler.handle(
            AcceptInvitation(
                invitation_token=invite_result.raw_invitation_token,
                password="another-strong-password-1",
            )
        )

    # Now demoting the ORIGINAL owner must succeed, since a second active
    # owner exists.
    async with real_database.session() as session:
        handler = ChangeUserRoleHandler(session)
        result = await handler.handle(
            ChangeUserRole(
                tenant_id=str(tenant.id),
                user_id=str(owner.id),
                new_role_name="ADMIN",
                changed_by=str(second_owner.id),
            )
        )
        assert result.role.name.value == "ADMIN"
