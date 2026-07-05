# Release Certification — NOVA GeoRisk Platform v1.2

**Certified for**: production deployment to `novaapi.novarex.co.tz` (cPanel hosting, shared PostgreSQL)
**Certification date**: 2026-07-05

This document is the final, consolidated production-readiness verdict for release v1.2. It summarizes evidence documented in full detail across `SECURITY_REVIEW.md`, `SECURITY_RETEST_REPORT.md`, `MIGRATION_EXTENSION_FIX_REPORT.md`, `PRODUCTION_READINESS_REPORT.md`, and `FINAL_RELEASE_CHECKLIST.md` — every figure below was independently re-verified against a freshly created PostgreSQL instance as part of this v1.2 packaging pass, not carried forward from memory or an earlier run.

---

## Test Count

| Metric | Value |
|---|---|
| Tests passing | **491** |
| Tests skipped | **1** (real Google Earth Engine connectivity — correctly skips; no live GCP service account credentials exist in any build/validation environment) |
| Tests failing | **0** |
| Static analysis | `ruff check .` clean · `mypy src/` clean (0 errors / 271 files) · `lint-imports` clean (4/4 contracts kept) |
| Test growth | 487 (v1.0) → 491 (v1.1, +4 tenant-isolation regression tests) → 491 (v1.2, no new tests — this release is a migration-portability fix with no new code paths to cover beyond what the existing suite already exercises) |

All 491 passing tests were re-run in full during v1.2 packaging against a **freshly created PostgreSQL instance with no `postgis`/`pgcrypto` extensions installed** — the same class of environment that caused the reported production failure — with zero regressions.

## Migration Count

| Metric | Value |
|---|---|
| Total migrations | **17** (`0000_baseline` → `0016_remote_sensing`) |
| Chain shape | Single linear chain — one head (`0016_remote_sensing`), zero branches, verified via `alembic heads`/`alembic branches`, not just visual inspection |
| Extensions required | **Zero.** `postgis` and `pgcrypto` are attempted best-effort in `0000_baseline.py` (harmless if present) but neither is used by any migration, model, or runtime code — traced exhaustively in `MIGRATION_EXTENSION_FIX_REPORT.md`. A failure to create either is caught per-extension (via `SAVEPOINT`) and logged as a warning; the migration chain completes regardless. |
| Verified against | A PostgreSQL instance confirmed to have **only** `plpgsql` installed (no `postgis`, no `pgcrypto`, no `vector` beyond what ships with the test build) — all 17 migrations applied cleanly; full `downgrade base` → `upgrade head` round-trip also verified. |

## Security Findings Status

| Finding | Severity | Status |
|---|---|---|
| Data Acquisition tenant-isolation gap (`CatalogDatasetHandler`/`ScheduleAcquisitionJobHandler` didn't verify cross-tenant `DatasetSource` ownership) | **High** | **Fixed and verified** (v1.1) — exploit reproduced against real PostgreSQL, confirmed blocked post-fix, re-confirmed again live over HTTP during v1.2 packaging. See `SECURITY_RETEST_REPORT.md`. |
| Migration chain aborts on PostgreSQL hosts without `postgis`/`pgcrypto` control files | **Deployment-blocking defect** (not a security finding, but equally launch-blocking) | **Fixed and verified** (v1.2) — this was the literal cause of the reported production failure. See `MIGRATION_EXTENSION_FIX_REPORT.md`. |
| No access-token revocation/denylist | Medium | Open — documented tradeoff, not blocking |
| No rate limiting at the application layer | Medium | Open — recommended mitigation: reverse-proxy layer (Nginx/Apache), not blocking |
| No upload size limit on `raw_content_base64` | Medium | Open — recommended mitigation: reverse-proxy request-body-size cap, not blocking |
| Length-only password complexity policy | Low | Open, not blocking |
| Unhandled-exception responses leak `str(exc)` to the client | Low | Open, not blocking |

**There are zero unresolved High-severity findings and zero unresolved deployment-blocking defects as of v1.2.** Every remaining open item is Medium/Low severity with a documented mitigation path, none of which prevents a safe initial production launch.

## Deployment Status

- **Entry point**: `passenger_wsgi.py` (Passenger-native ASGI, requires Passenger ≥ 6.0.9) with `startup.py` as a reverse-proxied-uvicorn fallback for older Passenger versions — both proven by a real boot against real PostgreSQL during this v1.2 pass.
- **Target runtime**: Python 3.12+ (codebase uses `enum.StrEnum`/`datetime.UTC`/`typing.Self`, all 3.11+ features) — confirm availability in cPanel's Python Selector before provisioning.
- **Database**: PostgreSQL, **any version/configuration, zero required contrib extensions** as of this release.
- **Live verification performed this pass**: `GET /health/live` → `200`; `GET /health/ready` → correctly reports database `"ok"` (Redis reported unavailable only because this sandbox has none — expected); `GET /api/v1/docs` → `404` (correctly hidden in production); full tenant-registration → login → dataset-source → cross-tenant-rejection → same-tenant-success flow exercised live over real HTTP.
- **Redis**: declared but not confirmed hard-required by every code path — verify availability on the target cPanel account before assuming full functionality (see `PRODUCTION_READINESS_REPORT.md`).

## Known Limitations (carried forward, none newly introduced by v1.2)

- No database-level Row-Level Security — tenant isolation is application-layer discipline (the one confirmed gap is now closed; no RLS defense-in-depth exists beyond that).
- No rate limiting at the application layer (mitigate at reverse-proxy layer).
- SMS notification channel is an honest stub — no real gateway (e.g. Twilio) integrated.
- GEE / USGS / NASA / Copernicus integrations require real credentials to function — all fail immediately and honestly when unconfigured, by design, never fabricating data.
- SPEI (drought index) is a documented water-balance approximation, not a full climatologically-fitted index.
- LST (land surface temperature) is only computed for Landsat (the one supported source with a real thermal band).
- No object storage (MinIO/S3) integration — Local Upload file bytes travel as base64 on the acquisition job record itself.
- No GDAL/rasterio — geometry math and remote-sensing feature extraction are pure Python over AOI-aggregate statistics, not per-pixel raster arrays.
- Unhandled-exception responses leak `str(exc)` detail to the client (Low severity, not yet fixed).

None of these are new to v1.2; all were previously documented in Sprints 0-14's own design decisions or the v1.0/v1.1 security review, and none block a safe initial production launch.

## Production Readiness Verdict

**CERTIFIED READY FOR PRODUCTION DEPLOYMENT** to `novaapi.novarex.co.tz`, conditional on the receiving team completing the pre-launch checklist below (infrastructure/operational confirmations, not code defects):

1. Confirm `ENVIRONMENT=production` is set in the real `.env` (activates the JWT-secret-default rejection guard).
2. Confirm Redis availability on the target cPanel account, or accept `/health/ready` reporting "degraded" for that one dependency.
3. Confirm Python 3.12 is actually selectable in cPanel's Python Application Manager.
4. Add reverse-proxy-level rate limiting and request-body-size caps (Nginx/Apache config — see `CPANEL_DEPLOYMENT_GUIDE.md`).
5. Provision real credentials only for the external integrations (SMTP / USGS / NASA / Copernicus / Google Earth Engine) this deployment actually needs live on day one.

This verdict is based on: 491 passing tests (0 failing) re-run against a freshly created, deliberately extension-less PostgreSQL instance; a clean 17-migration chain verified to require zero PostgreSQL extensions; zero unresolved High-severity security findings; a live, real-infrastructure re-confirmation of both shipped fixes (tenant isolation and migration portability) over actual HTTP; and clean static analysis across the entire codebase. Nothing in this certification was assumed or carried forward without independent re-verification during this v1.2 packaging pass.
