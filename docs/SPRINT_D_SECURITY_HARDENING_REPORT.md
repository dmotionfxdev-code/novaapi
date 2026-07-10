# Sprint D — Security & Production Hardening

**Scope**: close the remaining application-layer security/operational gaps identified in
`CAPABILITY_VERIFICATION_POST_SPRINT_C.md` §4, ahead of client UAT. Backend only. No
Analysis/FIRAS/WRRAS/Prediction/Validation/Risk-Layer formula or aggregate changes; no
frontend changes; API-compatible (every pre-existing endpoint's request/response shape and
status codes are unchanged; new behavior is additive).

---

## 1. Implementation Summary

### 1.1 Access Token Revocation

Access tokens are stateless JWTs — before this sprint, revoking a `RefreshToken` (already
implemented since Sprint 1 for logout/password-reset/suspend/deactivate) never invalidated
an already-issued *access* token, which stayed valid until its natural 8h expiry regardless.
This was the one confirmed Medium-severity gap in `RELEASE_CERTIFICATION.md`.

Two independent, deliberately different mechanisms now close it:

- **Bulk revocation** — `User.token_generation` (`domain/entities.py`), a per-user counter.
  `User.revoke_all_sessions()` increments it. Every issued access token embeds the value
  active at issue time as a real JWT claim (`"gen"`, `infrastructure/security.py`'s
  `JwtAccessTokenIssuer.issue`/`.decode`, via `AccessTokenClaims.token_generation`,
  `application/ports.py`). A token whose `gen` no longer matches the user's *current*
  counter is stale. Triggered by: password reset (`ResetPasswordHandler`), suspend
  (`SuspendUserHandler`), deactivate (`DeactivateUserHandler`), password change
  (`ChangePasswordHandler`), and the new explicit `POST /api/v1/auth/sessions/revoke-all`
  (`RevokeAllSessionsHandler`).
- **Single-session revocation (logout)** — a denylist keyed by the JWT's own `jti`
  (`RevokedAccessToken`, `domain/tokens.py`; table `identity.revoked_access_token`,
  migration `0019_security_hardening.py`). Logout ends *only* the caller's current session,
  never every session for that user — the bulk mechanism would be wrong here.
  `POST /api/v1/auth/logout` gained an *optional* decode of the caller's own
  `Authorization` header (`get_optional_decoded_access_token`,
  `interface/dependencies.py`) — if present, that specific token is revoked in addition to
  the refresh token; if absent, behavior is byte-for-byte identical to before this sprint
  (no `Authorization` header has ever been required to log out, and the endpoint stays
  idempotent).

Both checks live in **one place**, `get_current_claims`
(`contexts/identity/interface/dependencies.py`) — the dependency every authenticated route
already sits on top of, either directly (`get_current_user`) or indirectly
(`require_permission(...)`). This closes a second, quieter gap the same fix required: before
this sprint, `require_permission`-only routes *never* re-checked the database at all — a
suspended/deactivated user, or an explicitly revoked session, stayed fully authorized on any
permission-only route until natural token expiry (only `get_current_user`-based routes
re-read the user). `get_current_claims` now performs the `jti` denylist check, a fresh user
reload, the `is_login_eligible()` check, and the `token_generation` comparison — once, for
every authenticated route uniformly. The fetched `User` is cached on `request.state` so
`get_current_user` (which needs the full entity) doesn't re-query it a second time in the
same request.

### 1.2 Application Rate Limiting

New top-level module `src/georisk/rate_limiting.py` (deliberately *not* under `api.middleware`
or any `contexts.*` package — see §2). `RateLimiter` tries a Redis-backed fixed-window
counter first (`INCR`+`EXPIRE` via a pipeline, shared correctly across worker processes);
any exception from that call (Redis unreachable) falls back to an in-process
`_InMemoryWindowCounter` for that check, never failing the request. Wired onto all 7 required
endpoints:

| Endpoint | Bucket | Key | Default limit |
|---|---|---|---|
| `POST /api/v1/auth/token` (login) | `login` | client IP | 10/minute |
| `POST /api/v1/tenants` (registration) | `registration` | client IP | 5/hour |
| `POST /api/v1/auth/password-reset/request` + `/confirm` | `password-reset` | client IP | 5/hour |
| `POST /api/v1/auth/token/refresh` | `token-refresh` | client IP | 30/minute |
| `POST /api/v1/assessments/{id}/actions/start-workflow` + `.../stages/{stage}/actions/execute` | `analysis-execution` | tenant | 20/minute |
| `POST /api/v1/assessments/{id}/predictions/actions/run` | `prediction-execution` | tenant | 20/minute |
| `POST /api/v1/acquisition-jobs` (dataset/shapefile upload) | `upload` | tenant | 20/minute |

All 7 limits are `Settings` fields (`rate_limit_*`), finally consuming Sprint 0's long-unused
`redis_ratelimit_url`. A `RateLimitExceededError` (new, `shared_kernel/errors.py`) maps to
`429` with a `Retry-After` header (`api/middleware/error_handling.py`).

### 1.3 Exception Hardening

`api/middleware/error_handling.py`'s catch-all `Exception` handler previously returned
`str(exc)` and the real exception's class name straight to the client — the one confirmed
Low-severity leak in `RELEASE_CERTIFICATION.md`. It now always returns a fixed generic
message (`"An unexpected error occurred. Please contact support with this trace ID."`) and a
fixed generic type (`InternalServerError`), with the correct `500` status and the request's
real `traceId` — the actual exception is still logged in full server-side
(`logger.exception(...)`), unchanged. Every already-mapped domain error (400/401/403/404/
409/422/429) is untouched — those messages were already deliberately crafted to be safe.

### 1.4 Redis Graceful Degradation

Audited every Redis touchpoint: before this sprint, the *only* consumer was `/health/ready`'s
own ping. `/health/ready` treated a Redis failure identically to a database failure (503
"degraded" either way) — pulling a fully-functional instance out of an orchestrator's
rotation for a non-essential dependency. `api/routes/health.py` now distinguishes them:
database down → `503 unhealthy` (this instance genuinely cannot serve most traffic); Redis
down alone → `200 degraded` (still receiving traffic; rate limiting silently uses its
in-process fallback). Sprint D's two new Redis-touching features (rate limiter, and
originally-considered revocation cache — see §2) were both built with this same
degrade-don't-fail posture from the start.

### 1.5 Security Audit

Re-checked, against the current (post-Sprint-D) source, not from memory:

- **Tenant isolation** — `_assert_dataset_source_visible_to_tenant` (Data Acquisition,
  the v1.1-fixed gap) is intact; every Sprint D handler that loads a user by ID
  (`SuspendUserHandler`/`DeactivateUserHandler`) still calls `_assert_same_tenant` first;
  the new `RevokeAllSessionsHandler` is self-service-only (acts on `current_user.id` from
  the authenticated token, never an admin-supplied ID), so it has no cross-tenant surface to
  check in the first place.
  `grep`ped for raw SQL string interpolation (`text(f"..."`, `.execute(f"..."`) across
  `src/` — zero results; the only `text()` call anywhere is the health check's static
  `"SELECT 1"`. No SQL injection surface exists (100% SQLAlchemy ORM query construction).
- **Authentication/authorization** — new revocation checks return 401 via
  `AuthenticationFailedError` (already the correct classification `UserNotActiveError` used
  pre-Sprint-D — no status-code change for existing callers).
- **Upload validation** — Sprint B's Shapefile ZIP-completeness + genuine GIS parsing
  untouched; the new `upload` rate-limit bucket adds a volumetric defense layer on top,
  not a replacement.
- **API security** — rate-limiter keys are built only from `request.client.host` (the real
  TCP peer address, not an attacker-controlled header) or a JWT-verified `tenant_id`; no
  injection surface into the Redis key format.

No new findings; no regressions to any previously-closed item.

---

## 2. Key Security/Architecture Decisions

- **Two revocation mechanisms, not one.** A single "revoked-before timestamp" per user
  would have been simpler but cannot express "log out only this one session" (logout) versus
  "log out everywhere" (password reset/suspend/deactivate/explicit revoke-all) — both are
  explicit, distinct requirements. A wall-clock timestamp comparison was also considered and
  rejected: JWT `iat` has second-level precision while a bulk-revocation event has
  microsecond precision, creating a real race where a token issued in the same wall-clock
  second as a revocation event could be incorrectly rejected. An integer generation counter,
  compared for exact equality, has no such race.
- **`rate_limiting.py` lives at the top level, not under `api.middleware`.** It needs to be
  importable from `contexts.*.interface` route modules (to key by tenant) without those
  contexts reaching into the composition root (`georisk.api`) — which would invert the
  established composition-root pattern (`api` depends on contexts, never the reverse).
  Mirrors the existing precedent of `db.session.get_session`, already imported directly by
  every context's interface layer.
- **`rate_limiting.py` deliberately omits `from __future__ import annotations`**, unlike
  nearly every other module in this codebase. `rate_limit_by_tenant`'s inner dependency
  function puts a closure-captured variable inside an `Annotated[..., Depends(...)]`
  annotation; with postponed evaluation active, FastAPI cannot resolve that annotation back
  to the real `Depends` object (it only has access to the function's `__globals__`, not its
  closure), and silently mis-registers the parameter as a plain, "missing" query parameter.
  **Caught by actually running the full integration suite against real Postgres** — 27 tests
  failed with `"loc": ["query", "tenant_id"]` 422s the first time this file carried the
  future import — not assumed correct from reading the code; confirmed with an isolated
  minimal reproduction before applying the fix.
- **Revocation checks are 100% database-backed, not Redis-backed.** Given Redis
  unavailability is a *known, expected* condition on this platform's target hosting, making
  "a revoked token stays rejected" depend on Redis being up would be a correctness regression
  disguised as an optimization. The `jti` denylist table is tiny (grows only on explicit
  logout/revoke-all events) and the lookup is an indexed primary-key read — no caching layer
  was needed to keep this fast.
- **Registration and login share no rate-limit bucket**, and neither shares with
  password-reset/token-refresh — a burst of failed logins must not accidentally block a
  legitimate registration from the same IP, and vice versa.

---

## 3. Test Evidence

New test files:

- `tests/unit/test_identity_domain.py` — extended: `User.revoke_all_sessions()` bumps
  `token_generation`; `RevokedAccessToken.issue()` carries `jti`/user/tenant/expiry.
- `tests/unit/test_jwt_access_token_issuer.py` (new, 4 tests) — `gen`/`jti` claim
  round-trip; a legacy (pre-Sprint-D, no `gen` claim) token decodes as generation 0;
  `decode_expiry()` returns an already-past expiry without raising.
- `tests/unit/test_rate_limiting.py` (new, 5 tests) — in-memory counter window/scoping
  logic; Redis-path enforcement via a fake pipeline; **Redis-down fallback** via a client
  whose every call raises `ConnectionError`.
- `tests/unit/test_error_handling.py` (new, 4 tests) — an unhandled `RuntimeError` with a
  deliberately sensitive message never appears in the response; a `traceId` is still
  produced with no `TraceContextMiddleware` present; a recognized domain error's own safe
  message still passes through unchanged (regression guard); `RateLimitExceededError` → 429
  + `Retry-After`.
- `tests/integration/test_sprint_d_security_hardening.py` (new, 12 tests, real Postgres +
  real HTTP via `TestClient`) — revoked-access-token rejection after logout; logout is still
  idempotent with **no** `Authorization` header (pre-Sprint-D contract preserved); logout
  does **not** revoke a second, independent session's token; password reset revokes every
  previously-issued access token; **suspending a user revokes their access token even on a
  permission-only route** (the exact gap this sprint closes); the explicit revoke-all-sessions
  endpoint kills every active session including the caller's own; that endpoint requires
  authentication; login rate-limited to 429 with a tiny per-test override; `Retry-After`
  header present; two different rate-limit buckets are scoped independently; `/health/ready`
  reports `200 degraded` (not `503`) when only Redis is down; **login still works when Redis
  is completely unreachable**.

### Fresh validation run performed for this sprint

| Check | Result |
|---|---|
| Full suite (fresh PostgreSQL, migrations `0000`→`0019`, 20 revisions, single linear chain) | **560 passed, 1 skipped, 0 failed** (533 pre-Sprint-D + 27 new; skip = real GEE connectivity, unchanged) |
| `mypy src/` | Clean — 0 errors, 276 source files (275 pre-Sprint-D; +1 for `rate_limiting.py`) |
| `lint-imports` | **4/4 contracts kept** — including the peer-independence and identity-shared-kernel contracts this sprint's dependency-direction decision (§2) was designed around |
| `ruff check .` | Clean on all real source/test files |

---

## 4. Live HTTP Validation

Real `uvicorn` process, real Postgres, **Redis genuinely unreachable throughout**
(`redis_url`/`redis_ratelimit_url` pointed at `127.0.0.1:1`, connection-refused):

```
GET  /health/live  -> 200 {"status": "ok"}
GET  /health/ready -> 200 {"status": "degraded", checks: {database: "ok", redis: "error: ...Connection refused"}}
                      (NOT 503 — the fixed degraded/unhealthy split)

POST /api/v1/tenants           -> 201 (registration succeeds with Redis down)
POST /api/v1/auth/token        -> 200 (login succeeds with Redis down; rate limiter used its in-process fallback)
3x real FIRAS indicator dataset uploads -> all 201/200 COMPLETED (upload endpoint's own rate limit degraded gracefully)
POST .../actions/start-workflow -> 200 VALIDATED (Analysis execution succeeds with Redis down)
GET  .../predictions            -> 200 (Prediction router reachable, same rate-limited path)

GET  /api/v1/users/me (before logout) -> 200
POST /api/v1/auth/logout               -> 204
GET  /api/v1/users/me (same token, after logout) -> 401   <- revoked token rejected

3x POST /api/v1/auth/token (wrong password, under the real 10/min limit) -> 401, 401, 401 (not blocked)
```

A **second** live server instance, booted with `RATE_LIMIT_LOGIN_PER_MINUTE=3` (still with
Redis unreachable) to get genuine, non-pytest evidence of enforcement:

```
POST /api/v1/auth/token (wrong password) x4, real curl:
  attempt 1: 401
  attempt 2: 401
  attempt 3: 401
  attempt 4: 429   <- rate limit enforced live
    body: {"title":"RateLimitExceededError","status":429,
            "detail":"Too many requests — try again in 22 seconds",
            "traceId":"fe89d471-...", "errors":[]}
    headers: Retry-After: 22, X-Trace-Id: dc553b2a-...
```

---

## 5. Updated Passing Test Count

**560 passing, 1 skipped, 0 failing** (up from 533 at the post-Sprint-C baseline; +27 net new
Sprint D tests: 4 unit for JWT claims, 5 unit for the rate limiter, 4 unit for exception
hardening, 12 integration/HTTP, plus 2 extended in the existing domain test file).

---

## 6. Updated Production Readiness / Capability Matrix

See `PRODUCTION_READINESS_REPORT.md` (Deployment Risks table rows for access-token
revocation, rate limiting, and unhandled-exception leakage updated to "Fixed and verified")
and `CAPABILITY_VERIFICATION_POST_SPRINT_D.md` (new — supersedes
`CAPABILITY_VERIFICATION_POST_SPRINT_C.md`'s remaining-gaps section).

---

## 7. Remaining Production Gaps (after Sprint D)

Everything in Sprint D's own scope (§1) is now VERIFIED. What's left, unchanged from
`CAPABILITY_VERIFICATION_POST_SPRINT_C.md` and not part of this sprint's brief:

1. **SMS notification channel** — still an honest, unimplemented stub (no Twilio/real
   gateway). Out of scope for this sprint.
2. **GEE/USGS/NASA/Copernicus** — require real credentials; fail immediately and honestly
   when unconfigured, by design.
3. **No raster-ready output** — Sprint C's own documented, honest limitation (vector-only
   GIS dependencies); unrelated to this sprint.
4. **No CRS reprojection on ingest** — uploaded Shapefiles must already be in an accepted CRS.
5. **No object storage (MinIO/S3)** — uploaded file bytes still travel as base64 on the
   `AcquisitionJob` row itself.
6. **No per-feature/pixel risk grading within one Risk Layer** — Sprint C's own documented
   scope decision.
7. **The in-process rate-limiter fallback is per-worker-process, not fleet-wide.** Under a
   genuine multi-process/multi-instance deployment with Redis down, each process enforces
   its own approximate limit rather than one shared limit — an explicitly accepted,
   documented tradeoff (§2): still stops the dominant single-client abuse case, not a
   coordinated multi-connection one, in that specific (Redis-down) condition only.
8. **No access-token-family/device management UI** — a user can revoke all sessions or rely
   on logout revoking the current one, but there is no endpoint to list/name/selectively
   revoke individual *other* active sessions (e.g., "log out my phone but not my laptop").
   Not required by this sprint's brief; a natural follow-on if UAT asks for it.

None of items 1–6 are new; they were already open before this sprint and are unrelated to
its scope. Items 7–8 are new, honestly-documented boundaries of what Sprint D itself
introduced, not defects in it.
