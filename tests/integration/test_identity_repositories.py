"""Repository-level integration tests against a real Postgres instance —
confirms the domain<->ORM mapping round-trips correctly and that the
migration's seed data (roles/permissions) is actually present.
"""

from __future__ import annotations

import uuid

import pytest

from georisk.contexts.identity.domain.entities import Tenant, User
from georisk.contexts.identity.domain.value_objects import ContactInfo, RoleName, UserStatus
from georisk.contexts.identity.infrastructure.repositories import (
    SqlAlchemyRoleRepository,
    SqlAlchemyTenantRepository,
    SqlAlchemyUserRepository,
)

pytestmark = pytest.mark.integration


async def test_seeded_roles_have_expected_permissions(db_session) -> None:  # noqa: ANN001
    role_repo = SqlAlchemyRoleRepository(db_session)
    roles = await role_repo.list_all()
    assert {r.name for r in roles} == set(RoleName)

    owner = await role_repo.get_by_name(RoleName.OWNER)
    admin = await role_repo.get_by_name(RoleName.ADMIN)
    viewer = await role_repo.get_by_name(RoleName.VIEWER)
    assert owner is not None and admin is not None and viewer is not None
    assert admin.permissions <= owner.permissions
    assert len(viewer.permissions) < len(admin.permissions)


async def test_tenant_save_and_get_round_trips(db_session) -> None:  # noqa: ANN001
    unique = uuid.uuid4().hex[:8]
    tenant, _ = Tenant.register(
        name=f"Repo Test {unique}",
        slug=f"repo-test-{unique}",
        contact=ContactInfo(email="repo@test.example"),
    )
    repo = SqlAlchemyTenantRepository(db_session)
    await repo.save(tenant)
    await db_session.flush()

    fetched = await repo.get_by_id(tenant.id)
    assert fetched is not None
    assert fetched.name == tenant.name
    assert fetched.slug == tenant.slug
    assert fetched.contact.email == "repo@test.example"

    by_slug = await repo.get_by_slug(tenant.slug)
    assert by_slug is not None
    assert by_slug.id == tenant.id

    assert await repo.slug_exists(tenant.slug) is True
    assert await repo.slug_exists("does-not-exist") is False


async def test_user_save_get_and_optimistic_concurrency(db_session) -> None:  # noqa: ANN001
    unique = uuid.uuid4().hex[:8]
    tenant, _ = Tenant.register(
        name=f"UserRepo {unique}",
        slug=f"userrepo-{unique}",
        contact=ContactInfo(email="u@test.example"),
    )
    tenant_repo = SqlAlchemyTenantRepository(db_session)
    await tenant_repo.save(tenant)
    await db_session.flush()

    role_repo = SqlAlchemyRoleRepository(db_session)
    owner_role = await role_repo.get_by_name(RoleName.OWNER)
    assert owner_role is not None

    user, _ = User.create_owner(
        tenant_id=tenant.id,
        email=f"owner-{unique}@test.example",
        hashed_password="hash",
        owner_role=owner_role,
    )
    user_repo = SqlAlchemyUserRepository(db_session)
    await user_repo.save(user)
    await db_session.flush()

    fetched = await user_repo.get_by_id(user.id)
    assert fetched is not None
    assert fetched.email == user.email
    assert fetched.status == UserStatus.ACTIVE
    assert fetched.version == 0

    # Optimistic concurrency: saving with a stale expected_version must raise.
    fetched.suspend(changed_by="test")
    await user_repo.save(fetched, expected_version=0)
    await db_session.flush()

    from georisk.contexts.identity.domain.errors import OptimisticConcurrencyError

    stale = await user_repo.get_by_id(user.id)
    assert stale is not None
    stale.reactivate(changed_by="test")
    with pytest.raises(OptimisticConcurrencyError):
        await user_repo.save(stale, expected_version=0)  # already advanced to version 1 above


async def test_count_active_owners(db_session) -> None:  # noqa: ANN001
    unique = uuid.uuid4().hex[:8]
    tenant, _ = Tenant.register(
        name=f"Owners {unique}",
        slug=f"owners-{unique}",
        contact=ContactInfo(email="o@test.example"),
    )
    tenant_repo = SqlAlchemyTenantRepository(db_session)
    await tenant_repo.save(tenant)

    role_repo = SqlAlchemyRoleRepository(db_session)
    owner_role = await role_repo.get_by_name(RoleName.OWNER)
    assert owner_role is not None
    user_repo = SqlAlchemyUserRepository(db_session)

    owner1, _ = User.create_owner(
        tenant_id=tenant.id,
        email=f"o1-{unique}@test.example",
        hashed_password="h",
        owner_role=owner_role,
    )
    owner2, _ = User.create_owner(
        tenant_id=tenant.id,
        email=f"o2-{unique}@test.example",
        hashed_password="h",
        owner_role=owner_role,
    )
    await user_repo.save(owner1)
    await user_repo.save(owner2)
    await db_session.flush()

    assert await user_repo.count_active_owners(tenant.id) == 2

    owner2.suspend(changed_by="test")
    await user_repo.save(owner2, expected_version=0)
    await db_session.flush()

    assert await user_repo.count_active_owners(tenant.id) == 1
