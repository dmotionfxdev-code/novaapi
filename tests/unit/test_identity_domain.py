"""Domain-layer unit tests — pure logic, no I/O, no database."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from georisk.contexts.identity.domain.entities import Role, Tenant, User
from georisk.contexts.identity.domain.errors import IllegalUserStatusTransitionError
from georisk.contexts.identity.domain.tokens import (
    InvitationToken,
    PasswordResetToken,
    RefreshToken,
    RevokedAccessToken,
)
from georisk.contexts.identity.domain.value_objects import (
    ROLE_PERMISSIONS,
    ContactInfo,
    PermissionCode,
    RoleId,
    RoleName,
    TenantId,
    UserId,
    UserStatus,
)

pytestmark = pytest.mark.unit


def _role(name: RoleName) -> Role:
    return Role(id=RoleId.new(), name=name, description="", permissions=ROLE_PERMISSIONS[name])


# --- Tenant -----------------------------------------------------------------


def test_tenant_register_produces_active_tenant_and_event() -> None:
    tenant, event = Tenant.register(
        name="Acme Corp", slug="acme-corp", contact=ContactInfo(email="a@acme.test")
    )
    assert tenant.is_active is True
    assert tenant.slug == "acme-corp"
    assert event.tenant_id == str(tenant.id)
    assert event.slug == "acme-corp"


def test_contact_info_rejects_invalid_email() -> None:
    with pytest.raises(ValueError, match="not a valid email"):
        ContactInfo(email="not-an-email")


def test_tenant_deactivate_and_reactivate() -> None:
    tenant, _ = Tenant.register(name="Acme", slug="acme", contact=ContactInfo(email="a@acme.test"))
    tenant.deactivate()
    assert tenant.is_active is False
    tenant.reactivate()
    assert tenant.is_active is True


# --- User status machine -----------------------------------------------------


def test_invited_user_can_activate() -> None:
    role = _role(RoleName.ANALYST)
    user, _ = User.invite(
        tenant_id=TenantId.new(), email="new@acme.test", role=role, invited_by="admin"
    )
    assert user.status == UserStatus.INVITED
    assert user.is_login_eligible() is False

    event = user.activate(hashed_password="hashed")
    assert user.status == UserStatus.ACTIVE
    assert user.is_login_eligible() is True
    assert event.user_id == str(user.id)


def test_active_user_cannot_activate_again() -> None:
    role = _role(RoleName.ANALYST)
    tenant_id = TenantId.new()
    user, _ = User.create_owner(
        tenant_id=tenant_id, email="o@acme.test", hashed_password="h", owner_role=role
    )
    with pytest.raises(IllegalUserStatusTransitionError):
        user.activate(hashed_password="h2")


@pytest.mark.parametrize(
    ("from_status", "action"),
    [
        (UserStatus.ACTIVE, "suspend"),
        (UserStatus.ACTIVE, "deactivate_account"),
        (UserStatus.SUSPENDED, "reactivate"),
        (UserStatus.DEACTIVATED, "reactivate"),
    ],
)
def test_legal_status_transitions(from_status: UserStatus, action: str) -> None:
    role = _role(RoleName.ANALYST)
    tenant_id = TenantId.new()
    user, _ = User.create_owner(
        tenant_id=tenant_id, email="u@acme.test", hashed_password="h", owner_role=role
    )
    user.status = from_status  # test setup shortcut — entity is a plain mutable dataclass

    event = getattr(user, action)(changed_by="admin")
    assert event.old_status == from_status.value


def test_suspended_user_cannot_be_suspended_again() -> None:
    role = _role(RoleName.ANALYST)
    user, _ = User.create_owner(
        tenant_id=TenantId.new(), email="u@acme.test", hashed_password="h", owner_role=role
    )
    user.suspend(changed_by="admin")
    with pytest.raises(IllegalUserStatusTransitionError):
        user.suspend(changed_by="admin")


def test_deactivated_user_cannot_be_suspended() -> None:
    role = _role(RoleName.ANALYST)
    user, _ = User.create_owner(
        tenant_id=TenantId.new(), email="u@acme.test", hashed_password="h", owner_role=role
    )
    user.deactivate_account(changed_by="admin")
    with pytest.raises(IllegalUserStatusTransitionError):
        user.suspend(changed_by="admin")


def test_revoke_all_sessions_bumps_token_generation() -> None:
    role = _role(RoleName.ANALYST)
    user, _ = User.create_owner(
        tenant_id=TenantId.new(), email="u@acme.test", hashed_password="h", owner_role=role
    )
    assert user.token_generation == 0
    user.revoke_all_sessions()
    assert user.token_generation == 1
    user.revoke_all_sessions()
    assert user.token_generation == 2


def test_change_role_emits_event_with_old_and_new_role() -> None:
    viewer = _role(RoleName.VIEWER)
    admin = _role(RoleName.ADMIN)
    user, _ = User.create_owner(
        tenant_id=TenantId.new(), email="u@acme.test", hashed_password="h", owner_role=viewer
    )

    event = user.change_role(admin, changed_by="owner-1")
    assert event.old_role_name == RoleName.VIEWER.value
    assert event.new_role_name == RoleName.ADMIN.value
    assert user.role.name == RoleName.ADMIN


def test_has_permission_reflects_role() -> None:
    viewer = _role(RoleName.VIEWER)
    owner = _role(RoleName.OWNER)
    user, _ = User.create_owner(
        tenant_id=TenantId.new(), email="u@acme.test", hashed_password="h", owner_role=viewer
    )
    assert user.has_permission(PermissionCode.TENANT_MANAGE) is False

    user.role = owner
    assert user.has_permission(PermissionCode.TENANT_MANAGE) is True


def test_role_permission_seed_mapping_is_hierarchical_by_design() -> None:
    """Not a strict subset chain (ANALYST intentionally has the same grant
    as VIEWER in this sprint's seed), but OWNER must always be a superset
    of ADMIN, which is the property that actually matters for the
    "last owner" guard's reasoning to be sound.
    """
    assert ROLE_PERMISSIONS[RoleName.ADMIN] <= ROLE_PERMISSIONS[RoleName.OWNER]


# --- Tokens -------------------------------------------------------------


def test_refresh_token_is_active_until_expiry() -> None:
    token = RefreshToken.issue(user_id=UserId.new(), tenant_id=TenantId.new(), token_hash="h")
    assert token.is_active() is True


def test_refresh_token_inactive_after_expiry() -> None:
    token = RefreshToken.issue(user_id=UserId.new(), tenant_id=TenantId.new(), token_hash="h")
    future = datetime.now(UTC) + timedelta(days=31)
    assert token.is_active(now=future) is False


def test_refresh_token_inactive_after_revoke() -> None:
    token = RefreshToken.issue(user_id=UserId.new(), tenant_id=TenantId.new(), token_hash="h")
    token.revoke()
    assert token.is_active() is False


def test_password_reset_token_invalid_after_use() -> None:
    token = PasswordResetToken.issue(user_id=UserId.new(), tenant_id=TenantId.new(), token_hash="h")
    assert token.is_valid() is True
    token.mark_used()
    assert token.is_valid() is False


def test_invitation_token_expires() -> None:
    token = InvitationToken.issue(user_id=UserId.new(), tenant_id=TenantId.new(), token_hash="h")
    future = datetime.now(UTC) + timedelta(days=8)
    assert token.is_valid(now=future) is False


def test_revoked_access_token_issue_carries_jti_and_expiry() -> None:
    user_id, tenant_id = UserId.new(), TenantId.new()
    expires_at = datetime.now(UTC) + timedelta(hours=8)
    entry = RevokedAccessToken.issue(
        jti="a-jti-value", user_id=user_id, tenant_id=tenant_id, expires_at=expires_at
    )
    assert entry.jti == "a-jti-value"
    assert entry.user_id == user_id
    assert entry.tenant_id == tenant_id
    assert entry.expires_at == expires_at
    assert entry.revoked_at <= datetime.now(UTC)
