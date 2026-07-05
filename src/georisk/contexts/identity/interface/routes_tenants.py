"""Tenant registration — the one public, unauthenticated write endpoint
that creates state beyond a token (everything else mutating requires
``get_current_user``/``require_permission``)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from georisk.contexts.identity.application.commands import RegisterTenant
from georisk.contexts.identity.application.handlers_tenant import RegisterTenantHandler
from georisk.contexts.identity.application.ports import PasswordHasher
from georisk.contexts.identity.interface.dependencies import get_database, get_password_hasher
from georisk.contexts.identity.interface.schemas import (
    RegisterTenantRequest,
    RegisterTenantResponse,
    TenantResponse,
    UserResponse,
)
from georisk.db.session import Database

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.post("", response_model=RegisterTenantResponse, status_code=status.HTTP_201_CREATED)
async def register_tenant(
    body: RegisterTenantRequest,
    db: Annotated[Database, Depends(get_database)],
    password_hasher: Annotated[PasswordHasher, Depends(get_password_hasher)],
) -> RegisterTenantResponse:
    handler = RegisterTenantHandler(db, password_hasher)
    tenant, owner = await handler.handle(
        RegisterTenant(
            name=body.name,
            tenant_email=body.tenant_email,
            tenant_phone=body.tenant_phone,
            tenant_address=body.tenant_address,
            owner_email=body.owner_email,
            owner_password=body.owner_password,
        )
    )
    return RegisterTenantResponse(
        tenant=TenantResponse.from_domain(tenant), owner=UserResponse.from_domain(owner)
    )
