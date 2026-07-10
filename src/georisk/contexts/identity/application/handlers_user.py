"""User lifecycle command handlers — each one transaction, one aggregate
(``User``), per Application Layer §9. The "at least one OWNER remains"
invariant is enforced here, not on the ``User`` entity itself, because it
requires cross-aggregate knowledge (how many *other* users in the tenant
are OWNER) that a single ``User`` instance cannot have — see
``domain/entities.py``'s module docstring.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.application.commands import (
    AcceptInvitation,
    ChangePassword,
    ChangeUserRole,
    DeactivateUser,
    InviteUser,
    ReactivateUser,
    SuspendUser,
)
from georisk.contexts.identity.application.ports import OpaqueTokenGenerator, PasswordHasher
from georisk.contexts.identity.application.services import PasswordPolicy
from georisk.contexts.identity.domain.entities import User
from georisk.contexts.identity.domain.errors import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidOrExpiredTokenError,
    LastOwnerRemovalError,
    RoleNotFoundError,
    UserNotFoundError,
)
from georisk.contexts.identity.domain.events import (
    AllSessionsRevoked,
    PasswordChanged,
    UserStatusChanged,
)
from georisk.contexts.identity.domain.tokens import InvitationToken
from georisk.contexts.identity.domain.value_objects import RoleName, TenantId, UserId
from georisk.contexts.identity.infrastructure.repositories import (
    SqlAlchemyInvitationTokenRepository,
    SqlAlchemyRefreshTokenRepository,
    SqlAlchemyRoleRepository,
    SqlAlchemyUserRepository,
)
from georisk.db.outbox_writer import append_event


def _assert_same_tenant(user: User, tenant_id: TenantId) -> None:
    """Interim, application-layer tenant scoping (Roadmap Sprint 1 — real
    database-level enforcement via Row-Level Security lands in Sprint 11,
    Infrastructure Architecture §6). Every handler that loads a user by ID
    on behalf of an actor must confirm the target actually belongs to the
    actor's own tenant before acting on it, and must fail exactly like a
    "not found" — never revealing that a user with this ID exists in a
    *different* tenant (API Resource Model §9: existence is never leaked
    across tenants).
    """
    if user.tenant_id != tenant_id:
        raise UserNotFoundError(f"User {user.id} not found")


async def _assert_not_last_owner(
    user_repo: SqlAlchemyUserRepository, user: User, tenant_id: TenantId
) -> None:
    if user.role.name != RoleName.OWNER:
        return
    active_owners = await user_repo.count_active_owners(tenant_id)
    if active_owners <= 1:
        raise LastOwnerRemovalError(
            f"Tenant {tenant_id} must retain at least one active OWNER; "
            f"refusing to change the last one (user {user.id})"
        )


@dataclass(frozen=True, slots=True)
class InviteUserResult:
    user: User
    raw_invitation_token: str


class InviteUserHandler:
    def __init__(self, session: AsyncSession, token_generator: OpaqueTokenGenerator) -> None:
        self._session = session
        self._token_generator = token_generator

    async def handle(self, command: InviteUser) -> InviteUserResult:
        user_repo = SqlAlchemyUserRepository(self._session)
        role_repo = SqlAlchemyRoleRepository(self._session)
        invitation_repo = SqlAlchemyInvitationTokenRepository(self._session)

        if await user_repo.email_exists(command.email):
            raise EmailAlreadyRegisteredError(f"{command.email} is already registered")

        role = await role_repo.get_by_name(RoleName(command.role_name))
        if role is None:
            raise RoleNotFoundError(f"Role {command.role_name!r} does not exist")

        tenant_id = TenantId.from_string(command.tenant_id)
        user, event = User.invite(
            tenant_id=tenant_id, email=command.email, role=role, invited_by=command.invited_by
        )
        await user_repo.save(user)
        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=tenant_id.value,
        )

        raw_token = self._token_generator.generate()
        invitation = InvitationToken.issue(
            user_id=user.id,
            tenant_id=tenant_id,
            token_hash=self._token_generator.hash_token(raw_token),
        )
        await invitation_repo.save(invitation)

        await self._session.commit()
        return InviteUserResult(user=user, raw_invitation_token=raw_token)


class AcceptInvitationHandler:
    def __init__(
        self,
        session: AsyncSession,
        password_hasher: PasswordHasher,
        token_generator: OpaqueTokenGenerator,
    ) -> None:
        self._session = session
        self._password_hasher = password_hasher
        self._token_generator = token_generator

    async def handle(self, command: AcceptInvitation) -> User:
        PasswordPolicy.validate(command.password)

        invitation_repo = SqlAlchemyInvitationTokenRepository(self._session)
        user_repo = SqlAlchemyUserRepository(self._session)

        token_hash = self._token_generator.hash_token(command.invitation_token)
        invitation = await invitation_repo.get_by_token_hash(token_hash)
        if invitation is None:
            raise InvalidOrExpiredTokenError("Invitation token not found")
        invitation.assert_valid()

        user = await user_repo.get_by_id(invitation.user_id)
        if user is None:
            raise UserNotFoundError(f"User {invitation.user_id} not found")

        hashed_password = self._password_hasher.hash(command.password)
        event = user.activate(hashed_password=hashed_password)

        await user_repo.save(user, expected_version=user.version)
        invitation.mark_used()
        await invitation_repo.save(invitation)
        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=user.tenant_id.value,
        )
        await self._session.commit()
        return user


class ChangeUserRoleHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: ChangeUserRole) -> User:
        user_repo = SqlAlchemyUserRepository(self._session)
        role_repo = SqlAlchemyRoleRepository(self._session)

        user = await user_repo.get_by_id(UserId.from_string(command.user_id))
        if user is None:
            raise UserNotFoundError(f"User {command.user_id} not found")
        _assert_same_tenant(user, TenantId.from_string(command.tenant_id))

        new_role = await role_repo.get_by_name(RoleName(command.new_role_name))
        if new_role is None:
            raise RoleNotFoundError(f"Role {command.new_role_name!r} does not exist")

        if new_role.name != user.role.name:
            await _assert_not_last_owner(user_repo, user, user.tenant_id)

        event = user.change_role(new_role, changed_by=command.changed_by)
        await user_repo.save(user, expected_version=user.version)
        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=user.tenant_id.value,
        )
        await self._session.commit()
        return user


class SuspendUserHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: SuspendUser) -> User:
        user_repo = SqlAlchemyUserRepository(self._session)
        user = await user_repo.get_by_id(UserId.from_string(command.user_id))
        if user is None:
            raise UserNotFoundError(f"User {command.user_id} not found")
        _assert_same_tenant(user, TenantId.from_string(command.tenant_id))

        await _assert_not_last_owner(user_repo, user, user.tenant_id)

        event = user.suspend(changed_by=command.changed_by, reason=command.reason)
        user.revoke_all_sessions()
        await user_repo.save(user, expected_version=user.version)
        await self._revoke_sessions_and_append(user, event)
        return user

    async def _revoke_sessions_and_append(self, user: User, event: UserStatusChanged) -> None:
        refresh_repo = SqlAlchemyRefreshTokenRepository(self._session)
        await refresh_repo.revoke_all_active_for_user(user.id, reason="user suspended")
        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=user.tenant_id.value,
        )
        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=AllSessionsRevoked.event_type,
            payload=AllSessionsRevoked(
                user_id=str(user.id), tenant_id=str(user.tenant_id), reason="user suspended"
            ).payload(),
            tenant_id=user.tenant_id.value,
        )
        await self._session.commit()


class ReactivateUserHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: ReactivateUser) -> User:
        user_repo = SqlAlchemyUserRepository(self._session)
        user = await user_repo.get_by_id(UserId.from_string(command.user_id))
        if user is None:
            raise UserNotFoundError(f"User {command.user_id} not found")
        _assert_same_tenant(user, TenantId.from_string(command.tenant_id))

        event = user.reactivate(changed_by=command.changed_by)
        await user_repo.save(user, expected_version=user.version)
        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=user.tenant_id.value,
        )
        await self._session.commit()
        return user


class DeactivateUserHandler:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, command: DeactivateUser) -> User:
        user_repo = SqlAlchemyUserRepository(self._session)
        user = await user_repo.get_by_id(UserId.from_string(command.user_id))
        if user is None:
            raise UserNotFoundError(f"User {command.user_id} not found")
        _assert_same_tenant(user, TenantId.from_string(command.tenant_id))

        await _assert_not_last_owner(user_repo, user, user.tenant_id)

        event = user.deactivate_account(changed_by=command.changed_by, reason=command.reason)
        user.revoke_all_sessions()
        await user_repo.save(user, expected_version=user.version)

        refresh_repo = SqlAlchemyRefreshTokenRepository(self._session)
        await refresh_repo.revoke_all_active_for_user(user.id, reason="user deactivated")

        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=event.event_type,
            payload=event.payload(),
            tenant_id=user.tenant_id.value,
        )
        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=AllSessionsRevoked.event_type,
            payload=AllSessionsRevoked(
                user_id=str(user.id), tenant_id=str(user.tenant_id), reason="user deactivated"
            ).payload(),
            tenant_id=user.tenant_id.value,
        )
        await self._session.commit()
        return user


class ChangePasswordHandler:
    def __init__(self, session: AsyncSession, password_hasher: PasswordHasher) -> None:
        self._session = session
        self._password_hasher = password_hasher

    async def handle(self, command: ChangePassword) -> User:
        user_repo = SqlAlchemyUserRepository(self._session)
        user = await user_repo.get_by_id(UserId.from_string(command.user_id))
        if user is None:
            raise UserNotFoundError(f"User {command.user_id} not found")

        if user.hashed_password is None or not self._password_hasher.verify(
            command.current_password, user.hashed_password
        ):
            raise InvalidCredentialsError("Current password is incorrect")

        PasswordPolicy.validate(command.new_password)
        user.set_password(self._password_hasher.hash(command.new_password))
        user.revoke_all_sessions()

        await user_repo.save(user, expected_version=user.version)

        refresh_repo = SqlAlchemyRefreshTokenRepository(self._session)
        await refresh_repo.revoke_all_active_for_user(user.id, reason="password changed")

        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=PasswordChanged.event_type,
            payload=PasswordChanged(user_id=str(user.id), tenant_id=str(user.tenant_id)).payload(),
            tenant_id=user.tenant_id.value,
        )
        await append_event(
            self._session,
            aggregate_type="User",
            aggregate_id=str(user.id),
            event_type=AllSessionsRevoked.event_type,
            payload=AllSessionsRevoked(
                user_id=str(user.id), tenant_id=str(user.tenant_id), reason="password changed"
            ).payload(),
            tenant_id=user.tenant_id.value,
        )
        await self._session.commit()
        return user
