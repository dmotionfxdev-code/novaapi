"""RegisterTenant is the one deliberate exception to "one transaction per
command" (Application Layer §9): a brand-new Tenant and its first (Owner)
User are two separate aggregates, and the platform has no relay/event
mechanism yet (Roadmap Sprint 3) to sequence "create tenant, then react to
TenantRegistered by creating the owner" the way later sprints will. Rather
than force an artificial single-aggregate shape, this handler explicitly
orchestrates two sequential, independently-committed transactions — each
one internally consistent, exactly as Application Layer §9 requires per
step, with the two-step nature documented rather than hidden.

Known limitation, accepted for this sprint's scope: if the second step
(creating the owner) fails after the first (creating the tenant) has
already committed, the tenant is left without an owner. Recovering from
that is an operational action (a retry that finds the tenant already
exists, or manual intervention), not an automated compensating
transaction — building a full saga/compensation mechanism for one
bootstrap flow is disproportionate at this sprint's scope, and the
platform's later event-driven machinery (Sprint 3+) is the more natural
place to eventually generalize this if it becomes a live source of pain.
"""

from __future__ import annotations

import re
import secrets

from georisk.contexts.identity.application.commands import RegisterTenant
from georisk.contexts.identity.application.ports import PasswordHasher
from georisk.contexts.identity.application.services import PasswordPolicy
from georisk.contexts.identity.domain.entities import Tenant, User
from georisk.contexts.identity.domain.errors import (
    EmailAlreadyRegisteredError,
    TenantSlugAlreadyExistsError,
)
from georisk.contexts.identity.domain.value_objects import ContactInfo, RoleName
from georisk.contexts.identity.infrastructure.repositories import (
    SqlAlchemyRoleRepository,
    SqlAlchemyTenantRepository,
    SqlAlchemyUserRepository,
)
from georisk.db.outbox_writer import append_event
from georisk.db.session import Database


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "tenant"


class RegisterTenantHandler:
    def __init__(self, db: Database, password_hasher: PasswordHasher) -> None:
        self._db = db
        self._password_hasher = password_hasher

    async def handle(self, command: RegisterTenant) -> tuple[Tenant, User]:
        PasswordPolicy.validate(command.owner_password)

        tenant = await self._create_tenant(command)
        owner = await self._create_owner(tenant, command)
        return tenant, owner

    async def _create_tenant(self, command: RegisterTenant) -> Tenant:
        async with self._db.session() as session:
            tenant_repo = SqlAlchemyTenantRepository(session)

            base_slug = _slugify(command.name)
            slug = base_slug
            if await tenant_repo.slug_exists(slug):
                slug = f"{base_slug}-{secrets.token_hex(3)}"
                if await tenant_repo.slug_exists(slug):
                    raise TenantSlugAlreadyExistsError(
                        f"Could not derive a unique slug from {command.name!r}"
                    )

            contact = ContactInfo(
                email=command.tenant_email,
                phone=command.tenant_phone,
                address=command.tenant_address,
            )
            tenant, event = Tenant.register(name=command.name, slug=slug, contact=contact)

            await tenant_repo.save(tenant)
            await append_event(
                session,
                aggregate_type="Tenant",
                aggregate_id=str(tenant.id),
                event_type=event.event_type,
                payload=event.payload(),
                tenant_id=tenant.id.value,
            )
            await session.commit()
            return tenant

    async def _create_owner(self, tenant: Tenant, command: RegisterTenant) -> User:
        async with self._db.session() as session:
            user_repo = SqlAlchemyUserRepository(session)
            role_repo = SqlAlchemyRoleRepository(session)

            if await user_repo.email_exists(command.owner_email):
                raise EmailAlreadyRegisteredError(f"{command.owner_email} is already registered")

            owner_role = await role_repo.get_by_name(RoleName.OWNER)
            assert owner_role is not None, "OWNER role must be seeded by the identity migration"

            hashed_password = self._password_hasher.hash(command.owner_password)
            owner, event = User.create_owner(
                tenant_id=tenant.id,
                email=command.owner_email,
                hashed_password=hashed_password,
                owner_role=owner_role,
            )

            await user_repo.save(owner)
            await append_event(
                session,
                aggregate_type="User",
                aggregate_id=str(owner.id),
                event_type=event.event_type,
                payload=event.payload(),
                tenant_id=tenant.id.value,
            )
            await session.commit()
            return owner
