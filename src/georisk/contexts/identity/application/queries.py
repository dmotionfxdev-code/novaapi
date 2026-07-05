"""Query handlers — read-only, never mutate, never go through the command
pipeline (Application Layer §3/§4). Simple enough in this sprint to read
directly from the repositories rather than a separate projection.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.entities import Role, Tenant, User
from georisk.contexts.identity.domain.errors import TenantNotFoundError, UserNotFoundError
from georisk.contexts.identity.domain.value_objects import TenantId, UserId
from georisk.contexts.identity.infrastructure.repositories import (
    SqlAlchemyRoleRepository,
    SqlAlchemyTenantRepository,
    SqlAlchemyUserRepository,
)
from georisk.shared_kernel.types import CursorPage


class GetTenantQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, tenant_id: TenantId) -> Tenant:
        tenant = await SqlAlchemyTenantRepository(self._session).get_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFoundError(f"Tenant {tenant_id} not found")
        return tenant


class GetUserQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, user_id: UserId) -> User:
        user = await SqlAlchemyUserRepository(self._session).get_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"User {user_id} not found")
        return user


@dataclass(frozen=True, slots=True)
class ListUsersParams:
    tenant_id: TenantId
    limit: int = 25
    cursor: str | None = None


class ListUsersQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self, params: ListUsersParams) -> CursorPage[User]:
        limit = min(max(params.limit, 1), 100)
        users, next_cursor, has_more = await SqlAlchemyUserRepository(self._session).list_by_tenant(
            params.tenant_id, limit=limit, cursor=params.cursor
        )
        return CursorPage(items=users, next_cursor=next_cursor, has_more=has_more)


class ListRolesQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def handle(self) -> list[Role]:
        return await SqlAlchemyRoleRepository(self._session).list_all()
