"""User management routes — everything here except ``/invitations/accept``
requires an authenticated caller; role/status-changing actions additionally
require the specific permission named on each route (API Resource Model
§12's role×action matrix, enforced via ``require_permission``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
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
from georisk.contexts.identity.application.handlers_user import (
    AcceptInvitationHandler,
    ChangePasswordHandler,
    ChangeUserRoleHandler,
    DeactivateUserHandler,
    InviteUserHandler,
    ReactivateUserHandler,
    SuspendUserHandler,
)
from georisk.contexts.identity.application.ports import (
    AccessTokenClaims,
    OpaqueTokenGenerator,
    PasswordHasher,
)
from georisk.contexts.identity.application.queries import (
    GetUserQuery,
    ListUsersParams,
    ListUsersQuery,
)
from georisk.contexts.identity.domain.entities import User
from georisk.contexts.identity.domain.errors import UserNotFoundError
from georisk.contexts.identity.domain.value_objects import PermissionCode, UserId
from georisk.contexts.identity.interface.dependencies import (
    get_current_user,
    get_password_hasher,
    get_token_generator,
    require_permission,
)
from georisk.contexts.identity.interface.schemas import (
    AcceptInvitationRequest,
    ChangePasswordRequest,
    ChangeUserRoleRequest,
    DeactivateUserRequest,
    InviteUserRequest,
    InviteUserResponse,
    SuspendUserRequest,
    UserListResponse,
    UserResponse,
)
from georisk.db.session import get_session

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    return UserResponse.from_domain(current_user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_own_password(
    body: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    password_hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> Response:
    handler = ChangePasswordHandler(session, password_hasher)
    await handler.handle(
        ChangePassword(
            tenant_id=str(current_user.tenant_id),
            user_id=str(current_user.id),
            current_password=body.current_password,
            new_password=body.new_password,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("", response_model=InviteUserResponse, status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InviteUserRequest,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(PermissionCode.USER_INVITE))],
    session: Annotated[AsyncSession, Depends(get_session)],
    token_generator: Annotated[OpaqueTokenGenerator, Depends(get_token_generator)],
) -> InviteUserResponse:
    handler = InviteUserHandler(session, token_generator)
    result = await handler.handle(
        InviteUser(
            tenant_id=str(claims.tenant_id),
            email=body.email,
            role_name=body.role_name,
            invited_by=str(claims.user_id),
        )
    )
    return InviteUserResponse(
        user=UserResponse.from_domain(result.user), invitation_token=result.raw_invitation_token
    )


@router.post("/invitations/accept", response_model=UserResponse)
async def accept_invitation(
    body: AcceptInvitationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    password_hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
    token_generator: Annotated[OpaqueTokenGenerator, Depends(get_token_generator)],
) -> UserResponse:
    handler = AcceptInvitationHandler(session, password_hasher, token_generator)
    user = await handler.handle(
        AcceptInvitation(invitation_token=body.invitation_token, password=body.password)
    )
    return UserResponse.from_domain(user)


@router.get("", response_model=UserListResponse)
async def list_users(
    claims: Annotated[AccessTokenClaims, Depends(require_permission(PermissionCode.USER_VIEW))],
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=25, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> UserListResponse:
    query = ListUsersQuery(session)
    page = await query.handle(
        ListUsersParams(tenant_id=claims.tenant_id, limit=limit, cursor=cursor)
    )
    return UserListResponse.from_page(page)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    claims: Annotated[AccessTokenClaims, Depends(require_permission(PermissionCode.USER_VIEW))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    query = GetUserQuery(session)
    user = await query.handle(UserId.from_string(user_id))
    if user.tenant_id != claims.tenant_id:
        raise UserNotFoundError(f"User {user_id} not found")
    return UserResponse.from_domain(user)


@router.post("/{user_id}/actions/change-role", response_model=UserResponse)
async def change_user_role(
    user_id: str,
    body: ChangeUserRoleRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.USER_MANAGE_ROLE))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    handler = ChangeUserRoleHandler(session)
    user = await handler.handle(
        ChangeUserRole(
            tenant_id=str(claims.tenant_id),
            user_id=user_id,
            new_role_name=body.role_name,
            changed_by=str(claims.user_id),
        )
    )
    return UserResponse.from_domain(user)


@router.post("/{user_id}/actions/suspend", response_model=UserResponse)
async def suspend_user(
    user_id: str,
    body: SuspendUserRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.USER_MANAGE_STATUS))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    handler = SuspendUserHandler(session)
    user = await handler.handle(
        SuspendUser(
            tenant_id=str(claims.tenant_id),
            user_id=user_id,
            changed_by=str(claims.user_id),
            reason=body.reason,
        )
    )
    return UserResponse.from_domain(user)


@router.post("/{user_id}/actions/reactivate", response_model=UserResponse)
async def reactivate_user(
    user_id: str,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.USER_MANAGE_STATUS))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    handler = ReactivateUserHandler(session)
    user = await handler.handle(
        ReactivateUser(
            tenant_id=str(claims.tenant_id), user_id=user_id, changed_by=str(claims.user_id)
        )
    )
    return UserResponse.from_domain(user)


@router.post("/{user_id}/actions/deactivate", response_model=UserResponse)
async def deactivate_user(
    user_id: str,
    body: DeactivateUserRequest,
    claims: Annotated[
        AccessTokenClaims, Depends(require_permission(PermissionCode.USER_MANAGE_STATUS))
    ],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserResponse:
    handler = DeactivateUserHandler(session)
    user = await handler.handle(
        DeactivateUser(
            tenant_id=str(claims.tenant_id),
            user_id=user_id,
            changed_by=str(claims.user_id),
            reason=body.reason,
        )
    )
    return UserResponse.from_domain(user)
