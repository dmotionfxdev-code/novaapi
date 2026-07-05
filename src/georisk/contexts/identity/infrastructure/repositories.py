"""Concrete SQLAlchemy repositories — one per aggregate root (Application
Layer §1), implementing the Protocol interfaces declared in
``contexts/identity/domain/repositories.py``.
"""

from __future__ import annotations

from datetime import UTC

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from georisk.contexts.identity.domain.entities import Role, Tenant, User
from georisk.contexts.identity.domain.errors import OptimisticConcurrencyError
from georisk.contexts.identity.domain.tokens import (
    InvitationToken,
    PasswordResetToken,
    RefreshToken,
)
from georisk.contexts.identity.domain.value_objects import (
    RefreshTokenId,
    RoleId,
    RoleName,
    TenantId,
    UserId,
    UserStatus,
)
from georisk.contexts.identity.infrastructure import mappers
from georisk.contexts.identity.infrastructure.models import (
    InvitationTokenModel,
    PasswordResetTokenModel,
    RefreshTokenModel,
    RoleModel,
    TenantModel,
    UserModel,
)


class SqlAlchemyTenantRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, tenant_id: TenantId) -> Tenant | None:
        model = await self._session.get(TenantModel, tenant_id.value)
        return mappers.tenant_to_domain(model) if model else None

    async def get_by_slug(self, slug: str) -> Tenant | None:
        result = await self._session.execute(select(TenantModel).where(TenantModel.slug == slug))
        model = result.scalar_one_or_none()
        return mappers.tenant_to_domain(model) if model else None

    async def slug_exists(self, slug: str) -> bool:
        result = await self._session.execute(select(TenantModel.id).where(TenantModel.slug == slug))
        return result.scalar_one_or_none() is not None

    async def save(self, tenant: Tenant) -> None:
        model = await self._session.get(TenantModel, tenant.id.value)
        if model is None:
            model = TenantModel()
        mappers.apply_tenant_to_model(tenant, model)
        self._session.add(model)


class SqlAlchemyRoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, role_id: RoleId) -> Role | None:
        model = await self._session.get(RoleModel, role_id.value)
        return mappers.role_to_domain(model) if model else None

    async def get_by_name(self, name: RoleName) -> Role | None:
        result = await self._session.execute(select(RoleModel).where(RoleModel.name == name.value))
        model = result.scalar_one_or_none()
        return mappers.role_to_domain(model) if model else None

    async def list_all(self) -> list[Role]:
        result = await self._session.execute(select(RoleModel))
        return [mappers.role_to_domain(m) for m in result.scalars().all()]


class SqlAlchemyUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: UserId) -> User | None:
        model = await self._session.get(UserModel, user_id.value)
        return mappers.user_to_domain(model) if model else None

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(UserModel).where(UserModel.email == email))
        model = result.scalar_one_or_none()
        return mappers.user_to_domain(model) if model else None

    async def email_exists(self, email: str) -> bool:
        result = await self._session.execute(select(UserModel.id).where(UserModel.email == email))
        return result.scalar_one_or_none() is not None

    async def list_by_tenant(
        self, tenant_id: TenantId, *, limit: int, cursor: str | None
    ) -> tuple[list[User], str | None, bool]:
        """Cursor pagination (API Resource Model §6) keyed on ``(created_at,
        id)`` for a deterministic, stable ordering — the cursor encodes both
        so equal ``created_at`` values never produce duplicate/skipped rows.
        """
        import base64
        import json
        import uuid as uuid_module

        query = (
            select(UserModel)
            .where(UserModel.tenant_id == tenant_id.value)
            .order_by(UserModel.created_at, UserModel.id)
        )
        if cursor:
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            from datetime import datetime

            cursor_created_at = datetime.fromisoformat(decoded["created_at"])
            cursor_id = uuid_module.UUID(decoded["id"])
            query = query.where(
                (UserModel.created_at > cursor_created_at)
                | ((UserModel.created_at == cursor_created_at) & (UserModel.id > cursor_id))
            )
        query = query.limit(limit + 1)

        result = await self._session.execute(query)
        models = list(result.scalars().all())
        has_more = len(models) > limit
        models = models[:limit]
        users = [mappers.user_to_domain(m) for m in models]

        next_cursor = None
        if has_more and models:
            last = models[-1]
            payload = json.dumps({"created_at": last.created_at.isoformat(), "id": str(last.id)})
            next_cursor = base64.urlsafe_b64encode(payload.encode()).decode()

        return users, next_cursor, has_more

    async def count_active_owners(self, tenant_id: TenantId) -> int:
        result = await self._session.execute(
            select(func.count(UserModel.id))
            .join(RoleModel, UserModel.role_id == RoleModel.id)
            .where(
                UserModel.tenant_id == tenant_id.value,
                RoleModel.name == RoleName.OWNER.value,
                UserModel.status == UserStatus.ACTIVE.value,
            )
        )
        return int(result.scalar_one())

    async def save(self, user: User, *, expected_version: int | None = None) -> None:
        model = await self._session.get(UserModel, user.id.value)
        if model is None:
            model = UserModel(version=0)
            mappers.apply_user_to_model(user, model)
            self._session.add(model)
            return

        if expected_version is not None and model.version != expected_version:
            raise OptimisticConcurrencyError(
                f"User {user.id} was modified concurrently "
                f"(expected version {expected_version}, found {model.version})"
            )
        mappers.apply_user_to_model(user, model)
        model.version = model.version + 1


class SqlAlchemyRefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash(self, token_hash: str) -> RefreshToken | None:
        result = await self._session.execute(
            select(RefreshTokenModel).where(RefreshTokenModel.token_hash == token_hash)
        )
        model = result.scalar_one_or_none()
        return mappers.refresh_token_to_domain(model) if model else None

    async def save(self, token: RefreshToken) -> None:
        model = await self._session.get(RefreshTokenModel, token.id.value)
        if model is None:
            model = RefreshTokenModel()
        mappers.apply_refresh_token_to_model(token, model)
        self._session.add(model)

    async def revoke_all_active_for_user(
        self, user_id: UserId, *, reason: str
    ) -> list[RefreshTokenId]:
        from datetime import datetime

        result = await self._session.execute(
            select(RefreshTokenModel).where(
                RefreshTokenModel.user_id == user_id.value,
                RefreshTokenModel.revoked_at.is_(None),
            )
        )
        models = list(result.scalars().all())
        now = datetime.now(UTC)
        revoked_ids = []
        for model in models:
            model.revoked_at = now
            revoked_ids.append(RefreshTokenId(value=model.id))
        return revoked_ids


class SqlAlchemyPasswordResetTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        result = await self._session.execute(
            select(PasswordResetTokenModel).where(PasswordResetTokenModel.token_hash == token_hash)
        )
        model = result.scalar_one_or_none()
        return mappers.password_reset_token_to_domain(model) if model else None

    async def save(self, token: PasswordResetToken) -> None:
        model = await self._session.get(PasswordResetTokenModel, token.id.value)
        if model is None:
            model = PasswordResetTokenModel()
        mappers.apply_password_reset_token_to_model(token, model)
        self._session.add(model)


class SqlAlchemyInvitationTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_token_hash(self, token_hash: str) -> InvitationToken | None:
        result = await self._session.execute(
            select(InvitationTokenModel).where(InvitationTokenModel.token_hash == token_hash)
        )
        model = result.scalar_one_or_none()
        return mappers.invitation_token_to_domain(model) if model else None

    async def get_active_for_user(self, user_id: UserId) -> InvitationToken | None:
        result = await self._session.execute(
            select(InvitationTokenModel)
            .where(
                InvitationTokenModel.user_id == user_id.value,
                InvitationTokenModel.used_at.is_(None),
            )
            .order_by(InvitationTokenModel.created_at.desc())
        )
        model = result.scalars().first()
        return mappers.invitation_token_to_domain(model) if model else None

    async def save(self, token: InvitationToken) -> None:
        model = await self._session.get(InvitationTokenModel, token.id.value)
        if model is None:
            model = InvitationTokenModel()
        mappers.apply_invitation_token_to_model(token, model)
        self._session.add(model)
