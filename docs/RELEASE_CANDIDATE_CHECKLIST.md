# Release Candidate 1 (RC1) Checklist — NOVA GeoRisk Platform

**Scope lock in effect as of 2026-07-11**: no new features in either `georisk-platform` (backend) or
`georisk-frontend`. Only Bug fixes / Deployment fixes / Documentation / Performance improvements /
Security improvements / UX polishing. Any proposed change is classified first as **Bug**,
**Improvement**, or **New Feature** — New Feature work is rejected by default unless explicitly
approved out of band. Triggered by the backend passing its live Production Acceptance Test
(`DEPLOYMENT_ACCEPTANCE_REPORT.md`, 15/15 real capability areas over HTTP against the live Render
deployment).

Every item below reflects real, currently-verified state — not an aspirational target. Where
something is unverified or open, it says so explicitly rather than assuming it's fine.

---

## 1. Backend Deployment

| Item | Status |
|---|---|
| Live URL | `https://georisk-api-e6h7.onrender.com` — confirmed reachable, `/health/live` and `/health/ready` both `200` |
| Platform | Render, `georisk-api` web service (free plan), built from `docker/api/Dockerfile` via `render.yaml` Blueprint |
| Deployment audit | `DEPLOYMENT_AUDIT_RENDER_RAILWAY_FLYIO.md` — Render ranked #1 of 3 for this project; zero application code changes required for Render (only a `${PORT:-8000}` entrypoint fix, universal across all 3 platforms, not Render-specific) |
| Migrations | All 20 revisions (`0000_baseline` → `0019_security_hardening`) applied and confirmed at head against the live Postgres |
| **Known gap** | `preDeployCommand` (automatic migration-on-deploy) is **not supported on Render's free plan** — a hard validation rejection, not a soft downgrade. Migrations must be applied **manually** after any deploy that adds one, via Render's Shell/Jobs tab (`alembic upgrade head`), until `georisk-api`'s plan is upgraded to `starter`+ (at which point the commented-out line in `render.yaml` can be re-enabled) |
| Git state | Backend repo: clean, `main` branch, commit `e094afb` (needs `git push origin main` from a machine with GitHub credentials — this sandbox has none) |
| Production Acceptance Test | **Passed**, 15/15 areas, `DEPLOYMENT_ACCEPTANCE_REPORT.md` |

## 2. Frontend Deployment

| Item | Status |
|---|---|
| Package | `NOVA_GEORISK_FRONTEND_RC2.zip` + `CHECKSUMS.txt`, built from an isolated staging copy (Pest dev deps stripped) |
| Target | cPanel hosting (Laravel 12 + Livewire 3), per `georisk-frontend/docs/CPANEL_DEPLOYMENT_GUIDE.md` |
| Backend pointer | `config/georisk.php`'s `base_url` defaults to the live Render URL; `GEORISK_API_TIMEOUT`/`GEORISK_API_CONNECT_TIMEOUT` raised to 60s/10s to absorb Render free-tier cold starts (measured 42s) |
| Live-verified against Render | Yes — full Register→Login→Dashboard→Upload→Analysis→Risk Layer→Prediction→Validation→Reports→Notifications→Logout flow, brand-new tenant, all real (`PRODUCTION_DEPLOYMENT_REPORT_RC2.md`) |
| Bugs found and fixed during that verification | (1) `AuthApi::login()` now catches JWT signature/expiry exceptions cleanly instead of a raw 500 when `GEORISK_JWT_SECRET`-equivalent mismatches occur — **note**: the frontend does not itself hold a JWT secret; this refers to it correctly surfacing the *backend's* token-validation failures rather than crashing; (2) an `ApiClient::handle()` 422-parsing gap that silently discarded a domain-level string `detail` message — fixed |
| **Known gap** | Frontend repo currently has **3 uncommitted changes** (`.env.local-backup` deleted, `docs/PRODUCTION_DEPLOYMENT_REPORT_RC2.md` modified, 2 scratch verification scripts deleted) — needs a commit before this is a clean RC1 snapshot |
| **Known gap** | Production `APP_URL` for the frontend itself is still a placeholder (`https://your-domain.example` in `.env.example`) — no live public frontend URL confirmed yet; only the RC2 zip has been built and cPanel-deployment-documented |
| Local dev | Laravel dev server on port 8080 (not 8000); FastAPI backend on a `/tmp` scratch copy on port 8001 for local iteration — irrelevant to production, noted for continuity only |

## 3. Environment Variables

**Backend** (`georisk-platform`) — full reference: `.env.production.example`. Minimum viable production set: `ENVIRONMENT=production`, `DATABASE_URL`, `JWT_SECRET_KEY`, `CORS_ALLOWED_ORIGINS`. Everything else (Redis, SMTP, USGS/NASA/Copernicus, GEE, rate-limit overrides) has a safe default or fails honestly when unset.

| Variable | Set on Render? | Note |
|---|---|---|
| `ENVIRONMENT` | Yes (`production`) | Confirmed — `/api/v1/docs` correctly `404`s |
| `DATABASE_URL` | Yes (via `fromDatabase`) | Confirmed working post-fix (§4) |
| `JWT_SECRET_KEY` | Yes (`generateValue: true`) | Render-generated, never in source |
| `CORS_ALLOWED_ORIGINS` | **Placeholder** | `render.yaml` ships `https://REPLACE-WITH-YOUR-FRONTEND-DOMAIN.example` — **action needed**: set to the real frontend origin once one exists. Currently low-urgency since the frontend calls the backend server-side (Laravel-to-FastAPI), never via browser `fetch`, so browser CORS isn't actually exercised yet — but must be correct before any future direct-browser API usage |
| `REDIS_URL` / `REDIS_RATELIMIT_URL` | Yes (via `fromService`, `georisk-cache`) | Confirmed working |
| `GEE_SERVICE_ACCOUNT_EMAIL` / `_PRIVATE_KEY` / `GEE_PROJECT_ID` | Working | See §6 |
| `SMTP_*`, `USGS_*`, `NASA_*`, `COPERNICUS_*` | Unset | Honestly fail when unset — by design, not a gap |
| `RATE_LIMIT_*` (7 fields) | Unset (code defaults apply) | Defaults: login 10/min, registration 5/hr, password-reset 5/hr, token-refresh 30/min, analysis/prediction execution 20/min, upload 20/min |

**Frontend** (`georisk-frontend`) — `GEORISK_API_BASE_URL`, `GEORISK_API_TIMEOUT`/`_CONNECT_TIMEOUT`/`_RETRY_TIMES`/`_RETRY_SLEEP_MS` all confirmed set correctly for the live Render backend.

## 4. Database

- PostgreSQL, Render managed (`georisk-postgres`, free plan). **No PostGIS/pgcrypto extensions required** — geometry is JSONB, IDs are application-generated UUIDs (already verified on a stock, extension-less instance).
- 20/20 migrations applied, confirmed at head (`0019_security_hardening`).
- **Known gap (high priority)**: Render's **free-tier Postgres is auto-deleted 30 days after creation**, 1 GB cap. No paid upgrade has been made yet. This is the single highest-priority open item before this can be a real production deployment (as opposed to an extended verification window).
- Schema: 10 logical schemas (`identity`, `assessment`, `analysis`, `prediction`, `validation`, `reporting`, `notification`, `geospatial`, `data_acquisition`, `audit` — the last currently empty, see §14).

## 5. Redis

- Render managed Key Value (`georisk-cache`, free plan, 25 MB) — confirmed reachable (`/health/ready` → `redis: ok`).
- **Fully optional by design** — only two consumers exist (health-check ping, Sprint D's rate limiter), both gracefully degrade if Redis is unreachable (`/health/ready` reports `200 degraded`, not `503`; rate limiting silently falls back to an in-process counter). Live-verified with Redis genuinely unreachable during Sprint D validation.

## 6. Google Earth Engine (GEE)

- **Status: working.** Authentication is live and verified (the PEM-formatting issue and a subsequent JWT-signature mismatch — both traced to credential entry, not code — are resolved; confirmed via a real live acquisition job reaching Earth Engine's API).
- **Capability boundary, by design, not a gap**: this platform stores **statistical outputs** (per-band `reduceRegion` means and the spectral indices derived from them) as the authoritative product of a GEE acquisition — never full raster imagery. The raw pixel GeoTIFF download is a **best-effort, optional artifact**; nothing in Analysis, Prediction, Validation, or the frontend has ever consumed it (no raster/tile pipeline exists anywhere in this platform). Earth Engine's synchronous download has a fixed request-size limit that any AOI larger than a small test square exceeds at native resolution — a real defect this was until fixed (see below): it used to fail the *entire* acquisition even though the real, useful statistical output had already been computed. Fixed: the acquisition now completes successfully in that case, with the raster content honestly absent and the reason recorded in the job's provenance (`FetchResult.raster_skipped_reason`). Verified with new unit tests (`tests/unit/test_gee_connector.py`) proving all three cases — raster succeeds, raster exceeds the limit (statistics still returned), and a genuine pre-download Earth Engine failure still fails the job — plus two real-network integration tests in `tests/integration/test_gee_connectivity.py`.
- **Not a deployment blocker** — every other Data Acquisition path (Local Upload, and USGS/NASA/Copernicus whenever configured) is unaffected and already proven working.

## 7. Backups

- `scripts/backup_db.sh` exists and is a real, working `pg_dump`-based backup script (30-day retention, custom format) — but it is written for the **cPanel** deployment path (reads a local `.env` file, intended to run via cron on the same host) and **is not currently scheduled against the live Render database**.
- **Known gap (high priority)**: no backup/restore has been exercised against the live Render Postgres at all. Render's own paid Postgres plans include automated daily backups; the free plan's backup story has not been confirmed. Until either (a) the Postgres plan is upgraded and Render's built-in backups are confirmed enabled, or (b) `backup_db.sh` (or an equivalent) is adapted and scheduled against Render's external connection string, **there is no verified recovery path if this database is lost** — beyond the 30-day free-tier expiry risk in §4, this is independently the top backups-related action item.

## 8. Monitoring

- `OTEL_EXPORTER_ENDPOINT` is declared (OpenTelemetry instrumentation is wired into the app) but **unset** on Render — tracing currently exports to console/log output only, no external APM.
- Render's own dashboard provides basic built-in metrics (CPU, memory, request/response logs) — this is the only monitoring currently in place.
- **Known gap**: no alerting is configured (no uptime monitor, no error-rate alert, no notification on deploy failure). `CPANEL_DEPLOYMENT_GUIDE.md`'s suggested hourly health-check cron (§10 of that doc) was written for the cPanel path and has not been adapted for Render.

## 9. Logging

- Structured JSON logging via `python-json-logger`, `LOG_LEVEL` configurable (defaults `INFO`).
- Every log line carries a `traceId` (via `TraceContextMiddleware`) and `tenantId` where resolvable — confirmed in this session's own live smoke-test output.
- Render's dashboard provides a log viewer; retention window for the free plan has not been independently confirmed — check before relying on historical log lookback beyond a few days.
- Unhandled exceptions are logged in full server-side (`logger.exception(...)`) while the client only ever sees a safe generic message + `traceId` (Sprint D exception hardening) — confirmed working end-to-end in this session's acceptance test.

## 10. Rate Limiting

- Application-layer rate limiting (Sprint D) live-verified on Render with a real `curl`-driven `429` (`Retry-After: 22` header, safe error body) on the 4th rapid login attempt under a tightened test limit.
- Covers: login, registration, password reset, token refresh, analysis execution, prediction execution, upload — all 7 required endpoints.
- Redis-preferred, gracefully degrades to an in-process counter if Redis is unreachable — verified live with Redis genuinely down (registration/login/uploads all continued working).
- Default production limits are generous (§3 table) — not yet tuned against real traffic patterns, since there has been none yet.

## 11. Security

**Closed this cycle** (Sprint D, live-verified): genuine access-token revocation (logout, password reset, suspend, deactivate, explicit "revoke all sessions" — including closing the gap where permission-only routes never re-checked revocation at all), application rate limiting, unhandled-exception detail no longer leaked to clients, Redis-outage health-check now correctly distinguished from a database outage.

**Still open** (pre-existing, not regressions, carried forward from `RELEASE_CERTIFICATION.md`):
- No database-level Row-Level Security (tenant isolation is application-layer discipline — re-audited this session, confirmed intact, no injection surface found via a fresh `grep` for raw SQL string interpolation).
- Length-only password complexity policy.
- No CRS reprojection on Shapefile ingest (must already be an accepted CRS).
- No object storage (uploads travel as base64 in Postgres rows — a real, if currently harmless, scaling ceiling).
- SMS notification channel remains an honest, permanent stub.

## 12. Documentation

Current, real documentation in `georisk-platform/docs/`: `PRODUCTION_READINESS_REPORT.md`, `RELEASE_CERTIFICATION.md`, `SECURITY_REVIEW.md`, `SECURITY_RETEST_REPORT.md`, `MIGRATION_EXTENSION_FIX_REPORT.md`, `CPANEL_DEPLOYMENT_GUIDE.md` (superseded as the primary path by Render, kept for reference/fallback), `SPRINT_A/B/C/D_*_REPORT.md`, `CAPABILITY_VERIFICATION_POST_SPRINT_C.md` and `_D.md`, `DEPLOYMENT_AUDIT_RENDER_RAILWAY_FLYIO.md`, `DEPLOYMENT_ACCEPTANCE_REPORT.md`, this checklist. Frontend: `georisk-frontend/docs/` has its own per-wave reports plus `CPANEL_DEPLOYMENT_GUIDE.md` and `PRODUCTION_DEPLOYMENT_REPORT_RC2.md`.

**Known gap**: no single top-level "how the whole product fits together" document exists spanning both repos — each repo's docs are internally thorough but there is no combined architecture/runbook entry point. Documentation-only work, in scope under the RC1 lock, not yet done.

## 13. User Acceptance Testing

- **Technical/backend acceptance**: **done** — `DEPLOYMENT_ACCEPTANCE_REPORT.md`, 15/15 capability areas, real HTTP against the live deployment.
- **Frontend acceptance**: **done** — `PRODUCTION_DEPLOYMENT_REPORT_RC2.md`, full real user journey against the live Render backend.
- **Domain-expert / business UAT**: **not done.** `PRODUCTION_READINESS_REPORT.md` has explicitly disclaimed this distinction since v1.2: automated technical verification "does not constitute... a UAT sign-off from the Tanzania NOVA-FIRAS/NOVA-WRRAS domain experts." That sign-off has not happened at any point in this project's history and remains the outstanding business gate before a real launch, independent of anything technical in this checklist.

## 14. Known Limitations (consolidated)

1. Render free-tier Postgres auto-deletes after 30 days (§4) — **highest priority**.
2. No verified backup/restore against the live database (§7) — **highest priority**.
3. GEE now authenticates correctly and raster download is honestly optional (§6, fixed) — no action needed unless a future feature genuinely needs raw imagery, which would be new scope.
4. `CORS_ALLOWED_ORIGINS` still a placeholder (§3) — low urgency today, must fix before any browser-direct API usage.
5. No Activity Log HTTP endpoint anywhere in the backend — `contexts/audit/` is empty scaffolding (confirmed by direct inspection during the acceptance test); the frontend's own Activity Log page (Wave 10) already compensates for this honestly by assembling a feed from other real endpoints rather than a dedicated audit API.
6. No object storage — uploads are base64-in-Postgres.
7. SMS notification channel is a permanent, documented stub.
8. No raster/pixel-level output — vector-only GIS stack by design; the frontend's Raster Products panel already discloses this honestly rather than fabricating imagery.
9. No CRS reprojection on ingest.
10. No per-feature/pixel risk grading within a single Risk Layer (uniform `risk_index` per layer).
11. Render free-tier web service sleeps after 15 min idle (30-60s cold start) — frontend timeouts already tuned for this (§2).
12. Frontend repo has uncommitted changes pending (§2).
13. No domain-expert UAT sign-off yet (§13).
14. No alerting/uptime monitoring configured (§8).

None of these are regressions introduced by RC1 work — all are either pre-existing, already-documented platform characteristics or newly-surfaced-but-honestly-reported findings from this session's own live verification.

## 15. Rollback Procedure

**Backend (Render)**:
1. Render retains prior successful deploys — use the dashboard's **Rollback** action on `georisk-api` to redeploy the last known-good image immediately (fastest path, no rebuild).
2. If a rollback needs to go further back than Render's retained deploy history, `git revert` the offending commit(s) on `main` and push — Render auto-deploys from the connected branch.
3. **Migrations**: every migration in this project has a real `downgrade()` (verified by this project's own established discipline of a full `downgrade base` → `upgrade head` round-trip check in earlier release cycles). If a rollback needs to undo a schema change, run `alembic downgrade <previous_revision>` manually against the live database (same manual-Shell path as forward migrations, §1) — do this *before* rolling back the application code if the new code depends on the new schema, or *after* if the old code is being restored to run against a schema it still understands. Always confirm which direction is safe for the specific change before running it; this project's migrations are designed to be individually reversible, not to be blindly chained.
4. Database itself: **no verified restore path exists yet** (§7) — a rollback that requires restoring lost data, not just reverting code/schema, is not currently a solved procedure. Resolving §7 is a prerequisite for a trustworthy rollback story, not just for backups in the abstract.

**Frontend (cPanel)**:
1. Keep the previous `NOVA_GEORISK_FRONTEND_*.zip` release artifact and its `CHECKSUMS.txt` archived (per existing convention) before deploying a new one.
2. Re-upload the previous release's files and re-run its own deployment steps (`CPANEL_DEPLOYMENT_GUIDE.md`) to roll back — no database migrations are coupled to frontend releases (the frontend holds no schema of its own), so this is lower-risk and independent of the backend rollback steps above.

---

## Summary for RC1 Sign-Off

**Technically ready, operationally not yet hardened for real production traffic.** Every functional capability this checklist covers has been verified live, end-to-end, against the real deployed backend and frontend. GEE is now fully working, including a real bug fix (raster download made an honest, best-effort optional artifact rather than able to fail an entire acquisition) found and closed during this cycle. The open items are entirely in the *operational* category — data durability (30-day Postgres expiry + no backup path), monitoring/alerting, and a business-side UAT sign-off — not in application correctness. Recommend closing items 1-2 in §14 before treating this as more than an extended acceptance-testing deployment.
