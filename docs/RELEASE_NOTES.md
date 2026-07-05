# NOVA GeoRisk Platform — Release Notes

## v1.2 (current release)

**Release date**: 2026-07-05
**Target deployment**: `novaapi.novarex.co.tz` (cPanel hosting)

### What changed since v1.1

- **Fixed: migration chain failed on shared-hosting PostgreSQL with no `postgis`/`pgcrypto` control files installed.** Production deployment failed during `alembic upgrade head` with `extension "postgis" is not available` / `extension "pgcrypto" is not available` — `0000_baseline.py`'s `CREATE EXTENSION IF NOT EXISTS` statements aborted the entire migration transaction the moment either extension's `.control` file was missing from the server, which is the normal case on shared/managed PostgreSQL hosting. Traced exhaustively (every migration, every model, all runtime code) before changing anything: **neither extension is actually used anywhere** — every geometry column is plain JSONB (a deliberate Sprint 7 decision, confirmed via the geospatial module's own docstring), and every ID is generated application-side via `uuid.uuid4()`, never `pgcrypto`'s `gen_random_uuid()` (never called anywhere in the codebase). Fixed by making both extensions best-effort: each is attempted inside its own `SAVEPOINT`, and a failure is caught and logged as a warning rather than aborting the migration chain. Reproduced the exact production failure against a real PostgreSQL build genuinely missing both `.control` files, confirmed the patched migration completes all 17 migrations cleanly against it. Full trace, quantified determination, and before/after evidence in `MIGRATION_EXTENSION_FIX_REPORT.md`.
- No other code changes — no new features, no business-logic or formula changes, no architectural changes. This release exists solely to close the migration-portability defect blocking deployment on shared-hosting PostgreSQL.

### Validation Status (v1.2)

- 491 automated tests passing, 1 correctly skipped — re-run against a **freshly created PostgreSQL instance with no `postgis`/`pgcrypto` control files installed at all** (confirmed: only PostgreSQL's built-in `plpgsql` present), matching the reported production environment exactly, not simulated.
- `ruff`, `mypy`, and `import-linter` all clean.
- Migration chain re-verified against this same extension-less instance: single linear chain, `0000_baseline` → `0016_remote_sensing`, one head, zero branches, all 17 migrations apply cleanly (with both extensions honestly skipped via warning logs); full downgrade → re-upgrade round-trip also verified.
- `passenger_wsgi.py` re-booted via a real ASGI server against this same instance; both the extension-portability fix (migrations succeeded at all) and the tenant-isolation fix (re-confirmed live over real HTTP: cross-tenant attempt → `404`, same-tenant equivalent → `201`) verified together in one pass.
- Full detail: `FINAL_RELEASE_CHECKLIST.md`, `RELEASE_CERTIFICATION.md`

---

## v1.1

**Release date**: 2026-07-05
**Target deployment**: `novaapi.novarex.co.tz` (cPanel hosting)

### What changed since v1.0

- **Fixed: High-severity tenant-isolation gap in Data Acquisition.** `CatalogDatasetHandler`/`ScheduleAcquisitionJobHandler` never verified a referenced `DatasetSource`'s tenant ownership, allowing one tenant to catalog a dataset or schedule an acquisition job against another tenant's *private* dataset source. Fixed with a single-purpose visibility check (`_assert_dataset_source_visible_to_tenant`) that mirrors the codebase's existing tenant-check convention. Exploit reproduced against real PostgreSQL, confirmed blocked post-fix; legitimate access patterns (same-tenant, and any-tenant access to global sources) re-verified unaffected. 4 new permanent regression tests added. Full trace, quantified exploit, and before/after evidence in `SECURITY_RETEST_REPORT.md`.
- Test suite grew from 487 to **491 passing tests** (the 4 new tenant-isolation regression tests); 1 still correctly skipped (real GEE connectivity, no live credentials in the build environment).
- No other code changes — no new features, no business-logic or formula changes, no architectural changes. This release exists solely to close the one High-severity finding blocking production deployment.

### Validation Status (v1.1)

- 491 automated tests passing, 1 correctly skipped, re-run against a **freshly created** PostgreSQL instance as part of this release's packaging (not reused state from any prior validation run)
- `ruff`, `mypy`, and `import-linter` all clean
- Migration chain re-verified: single linear chain, `0000_baseline` → `0016_remote_sensing`, one head, zero branches, applies cleanly to a fresh database
- `passenger_wsgi.py` re-booted via a real ASGI server against the fresh PostgreSQL instance; the tenant-isolation fix re-confirmed live over real HTTP (cross-tenant attempt → `404`, same-tenant equivalent → `201`)
- Full detail: `FINAL_RELEASE_CHECKLIST.md`

---

## v1.0

**Release date**: 2026-07-05
**Target deployment**: `novaapi.novarex.co.tz` (cPanel hosting)

### What's in this release

A complete, ground-up rewrite of the NOVA GeoRisk platform (FastAPI + SQLAlchemy 2.0 async + PostgreSQL), covering Sprints 0-14:

- Identity & Access Management (JWT auth, refresh tokens, RBAC, password reset)
- Assessment lifecycle & Workflow Engine
- Validation (classification + regression metrics)
- FIRAS (flood) and WRRAS (wildfire) hazard strategies
- Geospatial (Area of Interest, Sampling Campaigns)
- Data Acquisition (dataset catalog, provenance, versioning)
- Prediction (correlation analysis + multiple linear regression)
- Reporting (cross-context report generation & finalization)
- Notification & Early Warning (alert rules, in-app/email/SMS-stub channels)
- Dashboard & Visualization (8 read-model projections)
- Data Acquisition Context extension: AcquisitionJob pipeline (Local Upload / USGS / NASA / Copernicus)
- Google Earth Engine & Remote Sensing Integration (6 sources, 5 preprocessing steps, 8 spectral indices)

### Validation Status (v1.0, at initial packaging)

- 487 automated tests passing, 1 correctly skipped (real GEE connectivity, no live credentials in the build environment)
- `ruff`, `mypy`, and `import-linter` all clean
- Migration chain verified: single linear chain, `0000_baseline` → `0016_remote_sensing`, applies cleanly to a fresh PostgreSQL database
- Deployment entry point (`passenger_wsgi.py`) proven against a real ASGI server + real PostgreSQL instance as part of this release's packaging

### Fixed in v1.0's deployment-readiness pass

- **`Settings.cors_allowed_origins` could not be loaded from a real `.env` file or environment variable** — a pydantic-settings quirk caused any value (including the documented comma-separated format) to raise a startup error. Fixed via `NoDecode` annotation; all prior functionality and tests unaffected. This was never caught in Sprints 0-14 because no prior test loaded `Settings` from a real file.
- Identified (but deliberately **not** fixed in v1.0, per that pass's "packaging only, no business-logic changes" scope): the Data Acquisition tenant-isolation gap closed above in v1.1.

## Known Limitations (current, see `PRODUCTION_READINESS_REPORT.md` for full detail)

- No database-level Row-Level Security (tenant isolation is application-layer discipline, with the one confirmed gap closed as of v1.1)
- No rate limiting at the application layer (recommended: reverse-proxy level)
- SMS notification channel is an honest stub (no real gateway integrated)
- GEE / USGS / NASA / Copernicus integrations require real credentials to function — all fail immediately and honestly when unconfigured, by design
- SPEI (drought index) is a documented water-balance approximation, not a full climatologically-fitted index
- No object storage (MinIO/S3) integration yet — Local Upload file bytes travel as base64 on the acquisition job record itself
- Unhandled-exception responses leak `str(exc)` detail to the client (Low severity, see `SECURITY_REVIEW.md` §6) — not yet fixed

## What these releases do NOT change

Per the deployment/security-fix phases' explicit scope: no new features, no business-logic changes, no formula changes, no architectural redesign. Every code change across v1.0 → v1.1 → v1.2 is a configuration-loading, access-control, or deployment-portability bug fix required for correct/safe operation in a real deployment — never a feature or behavior change.

## Documentation Index

| Document | Purpose |
|---|---|
| `docs/SECURITY_REVIEW.md` | Security audit findings, by severity |
| `docs/SECURITY_RETEST_REPORT.md` | Tenant-isolation fix: exact code path, exploit, fix, verification (v1.1) |
| `docs/MIGRATION_EXTENSION_FIX_REPORT.md` | postgis/pgcrypto portability fix: dependency trace, determination, fix, verification (v1.2) |
| `docs/PRODUCTION_READINESS_REPORT.md` | Completed modules, test coverage, known limitations, risks, recommendations |
| `docs/API_DEPLOYMENT_GUIDE.md` | Full endpoint reference, organized by context |
| `docs/CPANEL_DEPLOYMENT_GUIDE.md` | Step-by-step cPanel deployment for novaapi.novarex.co.tz |
| `docs/FINAL_RELEASE_CHECKLIST.md` | Evidence-backed pre-release verification results |
| `docs/RELEASE_CERTIFICATION.md` | Final production-readiness verdict (v1.2) |
| `.env.production.example` | Production environment variable template |
| `passenger_wsgi.py` / `startup.py` | ASGI entry points (Passenger-native / reverse-proxied uvicorn) |
| `deploy.sh` | Install → migrate → restart → health-check automation |
