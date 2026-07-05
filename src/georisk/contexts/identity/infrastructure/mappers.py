"""Maps between domain entities (contexts/identity/domain) and their
SQLAlchemy ORM representation (contexts/identity/infrastructure/models).
Kept as free functions, not methods on either side, so neither layer needs
to know about the other's existence.
"""

from __future__ import annotations

from georisk.contexts.identity.domain.entities import Role, Tenant, User
from georisk.contexts.identity.domain.tokens import (
    InvitationToken,
    PasswordResetToken,
    RefreshToken,
)
from georisk.contexts.identity.domain.value_objects import (
    Branding,
    ContactInfo,
    InvitationTokenId,
    PasswordResetTokenId,
    PermissionCode,
    RefreshTokenId,
    RoleId,
    RoleName,
    TenantId,
    UserId,
    UserStatus,
)
from georisk.contexts.identity.infrastructure.models import (
    InvitationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
    RoleModel,
    TenantModel,
    UserModel,
)


def role_to_domain(model: RoleModel) -> Role:
    return Role(
        id=RoleId(value=model.id),
        name=RoleName(model.name),
        description=model.description,
        permissions=frozenset(PermissionCode(p.code) for p in model.permissions),
    )


def tenant_to_domain(model: TenantModel) -> Tenant:
    return Tenant(
        id=TenantId(value=model.id),
        name=model.name,
        slug=model.slug,
        contact=ContactInfo(email=model.email, phone=model.phone, address=model.address),
        branding=Branding(logo_url=model.logo_url),
        is_active=model.is_active,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def apply_tenant_to_model(entity: Tenant, model: TenantModel) -> None:
    model.id = entity.id.value
    model.name = entity.name
    model.slug = entity.slug
    model.email = entity.contact.email
    model.phone = entity.contact.phone
    model.address = entity.contact.address
    model.logo_url = entity.branding.logo_url
    model.is_active = entity.is_active
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at


def user_to_domain(model: UserModel) -> User:
    return User(
        id=UserId(value=model.id),
        tenant_id=TenantId(value=model.tenant_id),
        email=model.email,
        hashed_password=model.hashed_password,
        role=role_to_domain(model.role),
        status=UserStatus(model.status),
        created_at=model.created_at,
        updated_at=model.updated_at,
        last_login_at=model.last_login_at,
        version=model.version,
    )


def apply_user_to_model(entity: User, model: UserModel) -> None:
    model.id = entity.id.value
    model.tenant_id = entity.tenant_id.value
    model.email = entity.email
    model.hashed_password = entity.hashed_password
    model.role_id = entity.role.id.value
    model.status = entity.status.value
    model.created_at = entity.created_at
    model.updated_at = entity.updated_at
    model.last_login_at = entity.last_login_at


def refresh_token_to_domain(model: RefreshTokenModel) -> RefreshToken:
    return RefreshToken(
        id=RefreshTokenId(value=model.id),
        user_id=UserId(value=model.user_id),
        tenant_id=TenantId(value=model.tenant_id),
        token_hash=model.token_hash,
        issued_at=model.issued_at,
        expires_at=model.expires_at,
        revoked_at=model.revoked_at,
        replaced_by_id=RefreshTokenId(value=model.replaced_by_id) if model.replaced_by_id else None,
    )


def apply_refresh_token_to_model(entity: RefreshToken, model: RefreshTokenModel) -> None:
    model.id = entity.id.value
    model.user_id = entity.user_id.value
    model.tenant_id = entity.tenant_id.value
    model.token_hash = entity.token_hash
    model.issued_at = entity.issued_at
    model.expires_at = entity.expires_at
    model.revoked_at = entity.revoked_at
    model.replaced_by_id = entity.replaced_by_id.value if entity.replaced_by_id else None


def password_reset_token_to_domain(model: PasswordResetTokenModel) -> PasswordResetToken:
    return PasswordResetToken(
        id=PasswordResetTokenId(value=model.id),
        user_id=UserId(value=model.user_id),
        tenant_id=TenantId(value=model.tenant_id),
        token_hash=model.token_hash,
        created_at=model.created_at,
        expires_at=model.expires_at,
        used_at=model.used_at,
    )


def apply_password_reset_token_to_model(
    entity: PasswordResetToken, model: PasswordResetTokenModel
) -> None:
    model.id = entity.id.value
    model.user_id = entity.user_id.value
    model.tenant_id = entity.tenant_id.value
    model.token_hash = entity.token_hash
    model.created_at = entity.created_at
    model.expires_at = entity.expires_at
    model.used_at = entity.used_at


def invitation_token_to_domain(model: InvitationTokenModel) -> InvitationToken:
    return InvitationToken(
        id=InvitationTokenId(value=model.id),
        user_id=UserId(value=model.user_id),
        tenant_id=TenantId(value=model.tenant_id),
        token_hash=model.token_hash,
        created_at=model.created_at,
        expires_at=model.expires_at,
        used_at=model.used_at,
    )


def apply_invitation_token_to_model(entity: InvitationToken, model: InvitationTokenModel) -> None:
    model.id = entity.id.value
    model.user_id = entity.user_id.value
    model.tenant_id = entity.tenant_id.value
    model.token_hash = entity.token_hash
    model.created_at = entity.created_at
    model.expires_at = entity.expires_at
    model.used_at = entity.used_at
