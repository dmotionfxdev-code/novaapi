"""Pydantic request/response models — independent of the SQLAlchemy models
and the domain entities (Architecture Redesign §9: "Pydantic schemas ≠ ORM
models"). Mapping from domain entities to these happens in this module via
small ``from_domain`` constructors, never by returning a domain object
directly from a route.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from georisk.contexts.identity.domain.entities import Role, Tenant, User
from georisk.shared_kernel.types import CursorPage

# --- Tenant -----------------------------------------------------------------


class RegisterTenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    tenant_email: EmailStr
    tenant_phone: str = ""
    tenant_address: str = ""
    owner_email: EmailStr
    owner_password: str = Field(min_length=12)


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    email: str
    phone: str
    address: str
    logo_url: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, tenant: Tenant) -> TenantResponse:
        return cls(
            id=str(tenant.id),
            name=tenant.name,
            slug=tenant.slug,
            email=tenant.contact.email,
            phone=tenant.contact.phone,
            address=tenant.contact.address,
            logo_url=tenant.branding.logo_url,
            is_active=tenant.is_active,
            created_at=tenant.created_at,
            updated_at=tenant.updated_at,
        )


# --- User ---------------------------------------------------------------


class UserResponse(BaseModel):
    id: str
    tenant_id: str
    email: str
    role_name: str
    status: str
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None

    @classmethod
    def from_domain(cls, user: User) -> UserResponse:
        return cls(
            id=str(user.id),
            tenant_id=str(user.tenant_id),
            email=user.email,
            role_name=user.role.name.value,
            status=user.status.value,
            created_at=user.created_at,
            updated_at=user.updated_at,
            last_login_at=user.last_login_at,
        )


class RegisterTenantResponse(BaseModel):
    tenant: TenantResponse
    owner: UserResponse


class UserListResponse(BaseModel):
    data: list[UserResponse]
    next_cursor: str | None
    has_more: bool

    @classmethod
    def from_page(cls, page: CursorPage[User]) -> UserListResponse:
        return cls(
            data=[UserResponse.from_domain(u) for u in page.items],
            next_cursor=page.next_cursor,
            has_more=page.has_more,
        )


class InviteUserRequest(BaseModel):
    email: EmailStr
    role_name: str


class InviteUserResponse(BaseModel):
    user: UserResponse
    # Deliberately present — see handlers_auth.py's module docstring on why
    # this differs from the password-reset flow. Forwarded out-of-band by
    # the inviting admin until Notification (Sprint 10) delivers it directly.
    invitation_token: str


class AcceptInvitationRequest(BaseModel):
    invitation_token: str
    password: str = Field(min_length=12)


class ChangeUserRoleRequest(BaseModel):
    role_name: str


class SuspendUserRequest(BaseModel):
    reason: str = ""


class DeactivateUserRequest(BaseModel):
    reason: str = ""


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12)


# --- Auth -----------------------------------------------------------------


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class RequestPasswordResetRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str = Field(min_length=12)


# --- Catalog ----------------------------------------------------------------


class RoleResponse(BaseModel):
    id: str
    name: str
    description: str
    permissions: list[str]

    @classmethod
    def from_domain(cls, role: Role) -> RoleResponse:
        return cls(
            id=str(role.id),
            name=role.name.value,
            description=role.description,
            permissions=sorted(p.value for p in role.permissions),
        )
