"""Read-only reference-data routes — the role/permission catalog."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.application.ports import AccessTokenClaims
from georisk.contexts.identity.application.queries import ListRolesQuery
from georisk.contexts.identity.domain.value_objects import PermissionCode
from georisk.contexts.identity.interface.dependencies import require_permission
from georisk.contexts.identity.interface.schemas import RoleResponse
from georisk.db.session import get_session

router = APIRouter(tags=["catalog"])


@router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    _claims: Annotated[AccessTokenClaims, Depends(require_permission(PermissionCode.ROLE_VIEW))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[RoleResponse]:
    query = ListRolesQuery(session)
    roles = await query.handle()
    return [RoleResponse.from_domain(r) for r in roles]
