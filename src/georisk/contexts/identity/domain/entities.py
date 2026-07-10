"""Identity aggregates: Tenant, User, and the Role/Permission reference
entities. Pure Python — no SQLAlchemy, no I/O (Clean Architecture's domain
layer, Architecture Redesign §9). Repositories (infrastructure layer) map
between these and their ORM representation.

Password hashing is deliberately NOT performed here — ``User`` stores only
an opaque ``hashed_password`` string and never sees a plaintext password or
a hashing algorithm; that's the application layer's ``PasswordHasher`` port
(application/ports.py), consistent with the domain layer having zero
framework/library awareness.

The "at least one OWNER per tenant" invariant is deliberately NOT enforced
inside ``User`` — a single ``User`` instance cannot know how many other
users in its tenant are OWNER, since that requires cross-aggregate
information. It's enforced by the command handler (LastOwnerRemovalError),
which queries the repository before invoking a role/status change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from georisk.contexts.identity.domain.errors import (
    IllegalUserStatusTransitionError,
)
from georisk.contexts.identity.domain.events import (
    TenantRegistered,
    UserActivated,
    UserInvited,
    UserRegistered,
    UserRoleChanged,
    UserStatusChanged,
)
from georisk.contexts.identity.domain.value_objects import (
    ROLE_PERMISSIONS,
    Branding,
    ContactInfo,
    PermissionCode,
    RoleId,
    RoleName,
    TenantId,
    UserId,
    UserStatus,
)


@dataclass(frozen=True, slots=True)
class Role:
    """Reference entity — system-seeded (migration), read-mostly. Not a
    full aggregate with its own command surface in this sprint; per-tenant
    custom roles are out of scope (value_objects.RoleName's docstring).
    """

    id: RoleId
    name: RoleName
    description: str
    permissions: frozenset[PermissionCode]

    def has_permission(self, code: PermissionCode) -> bool:
        return code in self.permissions


@dataclass(slots=True)
class Tenant:
    id: TenantId
    name: str
    slug: str
    contact: ContactInfo
    branding: Branding
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def register(
        cls, *, name: str, slug: str, contact: ContactInfo
    ) -> tuple[Tenant, TenantRegistered]:
        now = datetime.now(UTC)
        tenant = cls(
            id=TenantId.new(),
            name=name,
            slug=slug,
            contact=contact,
            branding=Branding(),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        event = TenantRegistered(tenant_id=str(tenant.id), name=tenant.name, slug=tenant.slug)
        return tenant, event

    def update_contact(self, contact: ContactInfo) -> None:
        self.contact = contact
        self.updated_at = datetime.now(UTC)

    def update_branding(self, branding: Branding) -> None:
        self.branding = branding
        self.updated_at = datetime.now(UTC)

    def deactivate(self) -> None:
        self.is_active = False
        self.updated_at = datetime.now(UTC)

    def reactivate(self) -> None:
        self.is_active = True
        self.updated_at = datetime.now(UTC)


# Legal User status transitions (Domain Model §6's FSM pattern, applied at
# context scale). A transition not listed here is illegal.
_LEGAL_STATUS_TRANSITIONS: dict[UserStatus, frozenset[UserStatus]] = {
    UserStatus.INVITED: frozenset({UserStatus.ACTIVE}),
    UserStatus.ACTIVE: frozenset({UserStatus.SUSPENDED, UserStatus.DEACTIVATED}),
    UserStatus.SUSPENDED: frozenset({UserStatus.ACTIVE, UserStatus.DEACTIVATED}),
    UserStatus.DEACTIVATED: frozenset({UserStatus.ACTIVE}),
}


@dataclass(slots=True)
class User:
    id: UserId
    tenant_id: TenantId
    email: str
    hashed_password: str | None  # None while status == INVITED, before AcceptInvitation
    role: Role
    status: UserStatus
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None
    # Optimistic concurrency (Application Layer §9) — incremented on every
    # save; checked by the repository, not by this entity.
    version: int = field(default=0)
    # Sprint D: bumped on every bulk session-revocation event (password
    # reset, suspend, deactivate, explicit "revoke all sessions"). Embedded
    # in every access token as the ``gen`` claim at issue time; a token
    # whose claim no longer matches this counter is stale and rejected —
    # see ``application/ports.py``'s ``AccessTokenClaims`` docstring.
    token_generation: int = field(default=0)

    @classmethod
    def invite(
        cls, *, tenant_id: TenantId, email: str, role: Role, invited_by: str
    ) -> tuple[User, UserInvited]:
        now = datetime.now(UTC)
        user = cls(
            id=UserId.new(),
            tenant_id=tenant_id,
            email=email,
            hashed_password=None,
            role=role,
            status=UserStatus.INVITED,
            created_at=now,
            updated_at=now,
        )
        event = UserInvited(
            user_id=str(user.id),
            tenant_id=str(tenant_id),
            email=email,
            role_name=role.name.value,
            invited_by=invited_by,
        )
        return user, event

    @classmethod
    def create_owner(
        cls, *, tenant_id: TenantId, email: str, hashed_password: str, owner_role: Role
    ) -> tuple[User, UserRegistered]:
        """The tenant-registration bootstrap case: there's no one to invite
        the first user, so they're created directly, active, with a
        password already set — distinct from ``invite()``.
        """
        now = datetime.now(UTC)
        user = cls(
            id=UserId.new(),
            tenant_id=tenant_id,
            email=email,
            hashed_password=hashed_password,
            role=owner_role,
            status=UserStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        event = UserRegistered(
            user_id=str(user.id),
            tenant_id=str(tenant_id),
            email=email,
            role_name=owner_role.name.value,
            status=user.status.value,
        )
        return user, event

    def _transition_status(
        self, new_status: UserStatus, *, changed_by: str, reason: str = ""
    ) -> UserStatusChanged:
        legal = _LEGAL_STATUS_TRANSITIONS.get(self.status, frozenset())
        if new_status not in legal:
            raise IllegalUserStatusTransitionError(
                f"User {self.id} cannot transition from {self.status} to {new_status}"
            )
        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.now(UTC)
        return UserStatusChanged(
            user_id=str(self.id),
            tenant_id=str(self.tenant_id),
            old_status=old_status.value,
            new_status=new_status.value,
            changed_by=changed_by,
            reason=reason,
        )

    def activate(self, *, hashed_password: str) -> UserActivated:
        if self.status != UserStatus.INVITED:
            raise IllegalUserStatusTransitionError(
                f"User {self.id} cannot accept an invitation from status {self.status}"
            )
        self.hashed_password = hashed_password
        self.status = UserStatus.ACTIVE
        self.updated_at = datetime.now(UTC)
        return UserActivated(user_id=str(self.id), tenant_id=str(self.tenant_id))

    def suspend(self, *, changed_by: str, reason: str = "") -> UserStatusChanged:
        return self._transition_status(UserStatus.SUSPENDED, changed_by=changed_by, reason=reason)

    def reactivate(self, *, changed_by: str) -> UserStatusChanged:
        return self._transition_status(UserStatus.ACTIVE, changed_by=changed_by)

    def deactivate_account(self, *, changed_by: str, reason: str = "") -> UserStatusChanged:
        return self._transition_status(UserStatus.DEACTIVATED, changed_by=changed_by, reason=reason)

    def change_role(self, new_role: Role, *, changed_by: str) -> UserRoleChanged:
        old_role = self.role
        self.role = new_role
        self.updated_at = datetime.now(UTC)
        return UserRoleChanged(
            user_id=str(self.id),
            tenant_id=str(self.tenant_id),
            old_role_name=old_role.name.value,
            new_role_name=new_role.name.value,
            changed_by=changed_by,
        )

    def set_password(self, hashed_password: str) -> None:
        self.hashed_password = hashed_password
        self.updated_at = datetime.now(UTC)

    def record_login(self) -> None:
        self.last_login_at = datetime.now(UTC)

    def revoke_all_sessions(self) -> None:
        """Bumps the counter every previously-issued access token's ``gen``
        claim is checked against — the bulk-revocation half of Sprint D's
        access-token revocation (the other half, single-session logout, is
        the ``revoked_access_token`` denylist keyed by ``jti`` instead;
        see ``domain/tokens.py``'s ``RevokedAccessToken``)."""
        self.token_generation += 1
        self.updated_at = datetime.now(UTC)

    def has_permission(self, code: PermissionCode) -> bool:
        return self.role.has_permission(code)

    def is_login_eligible(self) -> bool:
        return self.status == UserStatus.ACTIVE


def role_permissions_for_seed() -> dict[RoleName, frozenset[PermissionCode]]:
    """Exposes the single-source-of-truth role→permission mapping
    (value_objects.ROLE_PERMISSIONS) to the migration's seed step, so the
    seeded database data and any in-process check are never able to drift.
    """
    return ROLE_PERMISSIONS
