"""Tenant context resolution for logging/tracing correlation ONLY.

Roadmap Sprint 1: this middleware now decodes the JWT (if present) and
populates ``tenant_id_var`` so every log line for this request carries the
right tenant id (Infrastructure Architecture §23). It is deliberately
best-effort and non-blocking — a missing or invalid token here is *not*
rejected; public endpoints (login, tenant registration, password reset)
have no token at all, and this middleware runs on every request
regardless of whether the route requires authentication.

This middleware is NEVER the enforcement mechanism. Actual authentication
and authorization happen exclusively via the ``get_current_user`` /
``require_permission`` FastAPI dependencies
(contexts/identity/interface/dependencies.py) on routes that need them.
Row-Level Security (Infrastructure Architecture §6, Roadmap Sprint 11)
will add the database-level guarantee this middleware's context-setting
alone was always documented as not being.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from georisk.contexts.identity.infrastructure.security import JwtAccessTokenIssuer
from georisk.observability.logging import tenant_id_var
from georisk.settings import get_settings


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
        tenant_id: str | None = None

        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            raw_token = auth_header.removeprefix("Bearer ").strip()
            settings = get_settings()
            issuer = JwtAccessTokenIssuer(
                secret_key=settings.jwt_secret_key,
                algorithm=settings.jwt_algorithm,
                ttl_seconds=settings.jwt_access_token_ttl_seconds,
            )
            try:
                claims = issuer.decode(raw_token)
                tenant_id = str(claims.tenant_id)
            except Exception:  # noqa: BLE001 — best-effort only, see module docstring
                tenant_id = None

        token = tenant_id_var.set(tenant_id)
        try:
            response = await call_next(request)
        finally:
            tenant_id_var.reset(token)
        return response
