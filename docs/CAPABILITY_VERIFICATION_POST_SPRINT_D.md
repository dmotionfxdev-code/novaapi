# Capability Verification — Post Sprint D

**Supersedes**: `CAPABILITY_VERIFICATION_POST_SPRINT_C.md`. Same VERIFIED/PARTIAL/NOT
IMPLEMENTED scheme, re-run fresh against the current codebase (post-Sprint-D). Only rows
that changed since the Sprint C verification are reproduced in full below with new evidence;
every other row from that document is unchanged and re-confirmed by this sprint's full test
run (§0) — see that document for the complete pre-Sprint-D matrix (platform capabilities
15-19e).

---

## 0. Fresh validation run performed for this document

| Check | Result |
|---|---|
| Full test suite (fresh PostgreSQL, migrations `0000_baseline`→`0019_security_hardening`, 20 revisions, single linear chain) | **560 passed, 1 skipped, 0 failed** (533 at post-Sprint-C baseline; +27 new Sprint D tests) |
| `mypy src/` | Clean — 0 errors, **276** source files (275 post-Sprint-C; +1 for `rate_limiting.py`) |
| `lint-imports` | **4/4 contracts kept** |
| `ruff check .` | Clean on all real source/test files |
| Live server boot, **Redis genuinely unreachable** (`127.0.0.1:1`, connection-refused) | `GET /health/ready` → `200 degraded` (not `503`); registration, login, real FIRAS indicator uploads, and Analysis execution (`start-workflow` → `VALIDATED`) all succeeded anyway |
| Live end-to-end HTTP flow | tenant → login → logout → **same access token rejected (401)** on the very next call; a second live server instance with `RATE_LIMIT_LOGIN_PER_MINUTE=3` produced a genuine `429` with `Retry-After: 22` on the 4th real `curl` login attempt |

---

## 1. Capability Matrix — rows changed since Sprint C

| # | Capability | Status (Sprint C) | Status (Sprint D) | Evidence |
|---|---|---|---|---|
| 20 | **Access token revocation** — logout/password-reset/suspend/deactivate/explicit "revoke all sessions" genuinely invalidate previously-issued access tokens | **NOT IMPLEMENTED** (refresh tokens were revocable; access tokens stayed valid until natural 8h expiry) | **VERIFIED** | `User.token_generation`/`revoke_all_sessions()` (`domain/entities.py`), `RevokedAccessToken` jti-denylist (`domain/tokens.py`, table `identity.revoked_access_token`), both checked in `get_current_claims` (`interface/dependencies.py`). Live-verified: `GET /users/me` returns 200 before logout, 401 with the *exact same token* immediately after. `tests/integration/test_sprint_d_security_hardening.py` (12 tests) covers logout, password reset, suspend (specifically via a `require_permission`-only route), and the new `POST /auth/sessions/revoke-all` endpoint |
| 20b | Permission-only routes (`require_permission`, no `get_current_user`) re-check revocation/active-status | **NOT IMPLEMENTED** (only `get_current_user`-based routes re-read the database; a suspended user's token kept authorizing permission-only routes until expiry) | **VERIFIED** | Both dependencies now sit on the same `get_current_claims`, which performs the DB check unconditionally. `test_suspending_a_user_revokes_their_previously_issued_access_token` exercises exactly this — `GET /users/me` (a `get_current_user` route) — but the fix is dependency-tree-wide, not route-specific |
| 21 | **Application-layer rate limiting** (login, registration, password reset, token refresh, analysis/prediction execution, upload) | **NOT IMPLEMENTED** (confirmed gap, `SECURITY_REVIEW.md`) | **VERIFIED** | `src/georisk/rate_limiting.py`'s `RateLimiter` (Redis-preferred, in-process fallback), wired via `rate_limit_by_ip`/`rate_limit_by_tenant` onto all 7 required endpoints. Live-verified with real `curl`: 4th rapid login attempt returned genuine `429` with `Retry-After: 22`, `traceId`, and a safe error body |
| 21b | Rate limiting degrades gracefully when Redis is unreachable | N/A (didn't exist) | **VERIFIED** | `tests/unit/test_rate_limiting.py::test_rate_limiter_degrades_to_in_memory_when_redis_is_down` (a Redis client whose every call raises `ConnectionError`); live-verified end-to-end with Redis genuinely unreachable throughout an entire live smoke run (registration/login/uploads/Analysis execution all succeeded) |
| 22 | **Unhandled-exception detail leakage** — `str(exc)`/internal exception type reaching the client | **NOT IMPLEMENTED** (confirmed Low-severity gap, `SECURITY_REVIEW.md` §6) | **VERIFIED (fixed)** | `api/middleware/error_handling.py`'s catch-all handler now returns a fixed safe message + `InternalServerError` type + real `traceId`, never `str(exc)`; the real exception is still logged in full server-side. `tests/unit/test_error_handling.py::test_unhandled_exception_never_leaks_its_real_message` asserts a deliberately sensitive `RuntimeError` message never appears in the response body or headers |
| 23 | **Redis health-check granularity** — a Redis outage read identically to a database outage (`503` either way) | **PARTIAL** (existing gap, not previously scored) | **VERIFIED (fixed)** | `api/routes/health.py` now returns `503 unhealthy` only for a database failure; a Redis-only failure returns `200 degraded` — live-verified above |

All other rows (1-19e) from `CAPABILITY_VERIFICATION_POST_SPRINT_C.md` are unchanged and
re-confirmed by this sprint's full suite re-run (§0) — Sprint D touched only Identity's
auth/session machinery, the new `rate_limiting.py` module, `error_handling.py`, and
`health.py`; it made zero changes to Analysis, FIRAS, WRRAS, Prediction, Validation, or Risk
Layer generation, per this sprint's own explicit constraints.

---

## 2. What changed vs. the Sprint C baseline

Three rows move from NOT IMPLEMENTED to VERIFIED (access token revocation, permission-only
route revocation enforcement, application rate limiting), one gap is fixed (unhandled
exception leakage), and one previously-unscored behavior is now explicitly VERIFIED (Redis
health-check granularity). Test count: 533 (Sprint C) → **560 today**, 0 regressions.

---

## 3. Remaining Gaps Before Client UAT

Carried forward from `CAPABILITY_VERIFICATION_POST_SPRINT_C.md` §4, with the four items
Sprint D closed removed:

~~5. Redis unavailability degrades `/health/ready`~~ — **closed** (now correctly reports `degraded`, not `unhealthy`, and the app keeps operating).
~~6. No app-layer rate limiting~~ — **closed**.
~~7. No access-token revocation~~ — **closed**.
~~8. Unhandled-exception detail leakage~~ — **closed**.

**Still open, unrelated to this sprint's scope:**

1. SMS notification channel still an unimplemented stub.
2. GEE/USGS/NASA/Copernicus need real credentials.
3. No raster-ready output (vector-only GIS dependencies, documented).
4. No CRS reprojection on ingest.
5. No object storage (base64-on-row uploads).
6. No per-feature/pixel risk grading within one risk layer (uniform `risk_index` per layer).

**New, honestly-documented boundaries introduced by Sprint D itself (not defects):**

7. The in-process rate-limiter fallback is per-worker-process, not fleet-wide — under a
   multi-instance deployment with Redis simultaneously down, each process enforces its own
   approximate limit rather than one shared one. Still stops the dominant single-client abuse
   case in that condition.
8. No session/device management UI — a user can revoke all sessions or rely on logout for
   the current one, but there is no endpoint to list or selectively revoke one specific
   *other* active session.

None of items 1–6 are regressions or new — they were open before Sprint D and are outside
its brief. Items 7–8 are Sprint D's own scope decisions, not gaps in what was asked.
