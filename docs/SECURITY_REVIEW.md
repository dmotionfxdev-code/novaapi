# Security Review — NOVA GeoRisk Platform

**Scope**: pre-deployment security audit of `georisk-platform/` (Sprints 0-14) ahead of production release to `novaapi.novarex.co.tz`. This is a code-level review of what exists today, not a penetration test. Findings are graded by severity; each includes file:line citations so they can be independently verified.

---

## 1. Authentication (JWT)

- Access tokens: HS256, signed with `settings.jwt_secret_key`, 8-hour TTL (`src/georisk/settings.py:51-53`). Issued/decoded via PyJWT in `contexts/identity/infrastructure/security.py`.
- Refresh tokens: opaque, high-entropy, 30-day TTL; only a SHA-256 hash is persisted, never the raw token (`contexts/identity/domain/tokens.py`). Revoked on logout (`LogoutHandler`, `contexts/identity/application/handlers_auth.py`).
- The development-only JWT secret (`"dev-only-insecure-secret-change-me"`) is rejected by a Pydantic validator **only when `ENVIRONMENT=production`** (`settings.py:93-108`). This is load-bearing: if the production `.env` omits `ENVIRONMENT=production`, the app will silently accept the insecure default.

**FINDING (Medium) — no access-token revocation.** Access tokens are stateless JWTs with no denylist/`jti` check. Logout only revokes the *refresh* token — a stolen access token remains valid for up to 8 hours regardless of logout. `require_permission` trusts the permission claims embedded in the token rather than re-checking the database (`contexts/identity/interface/dependencies.py`). Acceptable for many APIs, but worth knowing: reducing `JWT_ACCESS_TOKEN_TTL_SECONDS` shortens this exposure window if it's a concern.

**FINDING (Medium) — no rate limiting anywhere.** `redis_ratelimit_url` is a declared Setting (`settings.py:26`) but nothing in `src/` actually uses it — there is no rate limiter on `POST /auth/token` (login) or any other endpoint. This means brute-force credential guessing and login enumeration are not mitigated at the application layer at all. **Recommended before go-live**: add rate limiting at the reverse-proxy layer (Apache/Nginx `mod_ratelimit`/`limit_req`) as a stopgap, since the app itself won't do it — see `CPANEL_DEPLOYMENT_GUIDE.md`.

**OK**: password reset (`POST /auth/password-reset/request`) returns an identical response whether or not the email exists (`handlers_auth.py`) — correctly hardened against account enumeration.

## 2. Password Handling

- Hashing: Argon2id via `argon2-cffi` (`contexts/identity/infrastructure/security.py`). Plaintext passwords are never persisted or logged (`domain/entities.py`).
- Password reset tokens: 1-hour TTL (`domain/tokens.py`).

**FINDING (Low) — length-only password policy.** `Field(min_length=12)` is the only complexity constraint on `owner_password`/`password`/`new_password` (`contexts/identity/interface/schemas.py`) — no character-class requirement. Argon2id's cost factor mitigates brute-force risk regardless, but a minimum entropy check (or at least rejecting common-password lists) is a reasonable pre-launch addition if user-chosen passwords are a realistic attack surface for this deployment.

## 3. Multi-Tenant Isolation

- `TenantContextMiddleware` is **logging/context only** — it does not enforce isolation (`src/georisk/api/middleware/tenant_context.py`, documented explicitly in its own docstring). Real enforcement happens per-handler/per-query at the application layer.
- The established, consistent pattern across every context: `repository.get_by_id(id)` fetches by primary key with **no tenant filter in the SQL**, then the calling handler/query checks `entity.tenant_id != claims.tenant_id` and raises a not-found error (never a distinguishable "forbidden," so cross-tenant ID guessing can't be used to detect existence). This pattern repeats identically across Assessment, Data Acquisition, Validation, Analysis, Notification, Reporting, Prediction, and Geospatial.

**FINDING (High) — RESOLVED, see `SECURITY_RETEST_REPORT.md`.** `CatalogDatasetHandler.handle` and `ScheduleAcquisitionJobHandler.handle` (`contexts/data_acquisition/application/handlers.py`) fetched a `DatasetSource` by ID and only checked `source is None` — they never verified `source.tenant_id` matched the caller's tenant. A tenant that discovered or guessed another tenant's private `DatasetSourceId` could successfully catalog a dataset or schedule an acquisition job that referenced it, unlike every other cross-aggregate reference in this codebase, which does check. **Fixed**: both handlers now call a new `_assert_dataset_source_visible_to_tenant` helper immediately after the existence check, rejecting (as a 404, matching the codebase's existing "fail like not-found" convention) any private cross-tenant source while still permitting same-tenant and global (`tenant_id=None`) sources. Verified against real PostgreSQL with a live exploit reproduction (blocked), the two legitimate access patterns (still allowed), a live HTTP re-test, and 4 new permanent regression tests — full detail, exact diff, and before/after evidence in `SECURITY_RETEST_REPORT.md`.

**Structural note**: isolation today is 100% application-layer discipline — there is no database-level Row-Level Security (RLS) as defense-in-depth. A single missed tenant check (like the one above) is directly exploitable. RLS is a reasonable post-launch hardening step, not a blocker.

## 4. Injection Risks

No findings. Every database access goes through SQLAlchemy Core/ORM with bound parameters; the few raw-SQL migration statements (`sa.text(...)` for permission-catalog seeding) consistently use named `:param` placeholders, never string interpolation. Confirmed by grep across `src/` and `migrations/` for f-string/`%`-built SQL — none found.

## 5. File Upload / Raw Content Handling

- Local Upload jobs carry their file content as base64 in `AcquisitionJob.raw_content_base64` (`Text` column). Content is validated structurally per declared format (GeoJSON/CSV/GeoTIFF-magic-bytes/Shapefile-magic-bytes/JSON — `contexts/data_acquisition/domain/validation.py`) before being persisted or cataloged.
- No `eval`/`exec`/`pickle.loads`/`subprocess`/unsafe-YAML anywhere in `src/` (confirmed by grep). Uploaded content is never written to a filesystem path derived from user input.

**FINDING (Medium) — no upload size limit.** `raw_content_base64` is an unconstrained `str | None` on both the request schema and the database column. Nothing caps the size of a scheduled job's payload, and there is no request-body-size middleware in `app.py`. A large base64 payload is a low-effort memory/storage DoS vector. **Recommended before go-live**: cap request body size at the reverse-proxy layer (`client_max_body_size` in Nginx / `LimitRequestBody` in Apache) — see `CPANEL_DEPLOYMENT_GUIDE.md`.

## 6. CORS, Error Handling, API Documentation Exposure

- CORS origins are configurable via `CORS_ALLOWED_ORIGINS` (not hardcoded to `*`), combined with `allow_credentials=True`. **This is fine as shipped, but is a footgun for the operator**: if `CORS_ALLOWED_ORIGINS=*` is ever set in the production `.env`, that combination is a real cross-origin credential-leak vulnerability. The production `.env.production.example` template ships with explicit origins for exactly this reason — do not change it to `*`.
- `/docs` and `/openapi.json` are only exposed when `not settings.is_production` (`app.py`) — confirmed the OpenAPI surface is hidden in production as intended, contingent on `ENVIRONMENT=production` actually being set.

**FINDING (Low) — unhandled-exception responses leak exception text.** The generic exception handler (`api/middleware/error_handling.py`) logs the full exception server-side (correct) but also returns `"detail": str(exc)` in the JSON body to the client. The code's own comment states the intent is an opaque 500 with only a trace ID — the implementation doesn't match that intent for this one path. In practice this means an unexpected internal error (a driver error message, an internal object repr, etc.) could be visible to an API caller. **Recommended before go-live**: strip `str(exc)` from the client-facing body for the generic/unhandled-exception path (keep it in the server log only) — this is a small, contained fix, not a redesign.

## 7. Secrets Handling

- `.env` and `*.env.local` are gitignored (`.gitignore`). No hardcoded high-entropy secrets found in `src/` beyond clearly-named, clearly-commented dev-only placeholders (`jwt_secret_key`'s default, `storage_secret_key`'s dev default) — both are `Settings` fields, overridable via environment, never hardcoded elsewhere.
- All optional third-party integrations (SMTP, USGS/NASA/Copernicus, GEE) default to `None`/unconfigured and fail immediately and honestly rather than attempting a connection with a guessed credential — there is nothing to accidentally leak here because nothing is hardcoded.

---

## Summary Table

| # | Area | Finding | Severity | Blocking for launch? |
|---|------|---------|----------|----------------------|
| 1 | Auth | No access-token revocation/denylist | Medium | No (documented tradeoff) |
| 1 | Auth | No rate limiting anywhere | Medium | **Recommended: mitigate at reverse proxy** |
| 2 | Passwords | Length-only complexity policy | Low | No |
| 3 | Tenant isolation | `CatalogDatasetHandler`/`ScheduleAcquisitionJobHandler` didn't verify `DatasetSource.tenant_id` | **High** | **Fixed — see `SECURITY_RETEST_REPORT.md`** |
| 4 | Injection | None found | — | — |
| 5 | File upload | No size limit on `raw_content_base64` | Medium | **Recommended: cap at reverse proxy** |
| 6 | CORS/errors | Unhandled-exception responses leak `str(exc)` | Low | Recommended |
| 7 | Secrets | None found | — | — |

**Bottom line**: the platform's security posture is solid in the areas that are hardest to get right (injection safety, password hashing, secret handling, honest-failure discipline for unconfigured integrations). The one **High** finding (tenant-isolation gap in Data Acquisition's dataset-source references) has been **fixed and verified** — see `SECURITY_RETEST_REPORT.md` for the full trace, exploit reproduction, fix, and re-verification evidence. **There are no remaining High-severity findings blocking production deployment.** Everything else in this document remains a hardening recommendation, not a launch blocker.
