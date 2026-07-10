# Production Readiness Report — NOVA GeoRisk Platform v1.2

**Prepared for**: deployment to `novaapi.novarex.co.tz` (cPanel hosting)
**Covers**: Sprints 0-14, all validated against real embedded PostgreSQL per-sprint (not assumed correct from review alone), plus the v1.1 tenant-isolation security fix (`SECURITY_RETEST_REPORT.md`), the v1.2 postgis/pgcrypto migration-portability fix (`MIGRATION_EXTENSION_FIX_REPORT.md`), and post-v1.2 Sprints A/B/C/D (real data integration, real Shapefile import, real risk-layer generation, and security/production hardening — see `SPRINT_D_SECURITY_HARDENING_REPORT.md` and `CAPABILITY_VERIFICATION_POST_SPRINT_D.md` for the current, superseding state of this report's module table and risk list)

---

## 1. Completed Modules

| # | Context | Key capability |
|---|---------|-----------------|
| 1 | Identity & Access Management | Tenant/User/Role/Permission, JWT auth + refresh tokens, Argon2id passwords, password reset, RBAC |
| 2 | Assessment | Assessment aggregate, 7-state lifecycle FSM (DRAFT→READY→RUNNING→VALIDATED→REPORTED→ARCHIVED, +CANCELLED) |
| 3 | Workflow Engine | WorkflowTemplate DAG (cycle detection), stage orchestration inside Assessment |
| 4 | Validation | ValidationRun aggregate, classification metrics (accuracy/precision/recall/F1/kappa/ROC-AUC) |
| 5 | FIRAS Strategy | Flood hazard: Hazard/Exposure/Vulnerability/Risk(multiplicative)/Resilience, EWM-weighted indicators |
| 6 | WRRAS Strategy | Wildfire hazard: multiplicative WRI, equal-weight WVI/WII, optional Fire Regime/BOP/Burn Severity |
| 7 | Geospatial | AreaOfInterest (versioned), SamplingCampaign (stratified/simple random) |
| 8 | Dataset Management | DatasetSource/Dataset/PredictorVariable/VariableSelection catalog, provenance, versioning |
| 9 | Prediction | Correlation (Pearson/Spearman/Kendall) + Multiple Linear Regression, pure-Python (no numpy) |
| 10 | Reporting | Report generation/finalization, cross-context snapshot aggregation |
| 11 | Regression Validation | RMSE/MAE/MSE/R²/Adjusted R² extension to Validation, integrated with Prediction |
| 12 | Notification & Early Warning | AlertRule/NotificationSubscription/Notification, threshold-based alert evaluation, In-App/Email/SMS(stub) channels |
| 13 | Dashboard & Visualization | 8 read-model projections (Executive/FIRAS/WRRAS/Prediction/Validation/Alert/Dataset/Workspace), no persistence of its own |
| 14 | Data Acquisition | AcquisitionJob (SCHEDULED→RUNNING→COMPLETED/FAILED), ProviderRegistry, Local Upload / USGS / NASA / Copernicus providers |
| 15 | GEE & Remote Sensing | Real Earth Engine connector, 6 sources, 5 preprocessing steps, 8 spectral indices, AOI-based processing |

All 15 areas are implemented, wired into a single FastAPI application (`georisk.api.app:create_app`), and share one PostgreSQL database (11 logical schemas, one per bounded context) via 17 linear Alembic migrations (`0000_baseline` → `0016_remote_sensing`, verified as a single clean chain with `alembic heads`/`alembic history` — no branches, no gaps, no duplicate revisions). As of v1.2, the migration chain requires **no PostgreSQL extensions at all** — `postgis`/`pgcrypto` are attempted best-effort in `0000_baseline.py` but neither is actually used anywhere in the platform (see `MIGRATION_EXTENSION_FIX_REPORT.md`), so the chain applies cleanly on a stock PostgreSQL install with zero contrib extensions.

## 2. Test Coverage

- **Current (post-Sprint-D): 560 tests passing, 1 skipped, 0 failing** — see `CAPABILITY_VERIFICATION_POST_SPRINT_D.md` for the fresh, independently re-run evidence. The count below (491) is the original v1.2 baseline this report was first written against; retained for history.
- **491 tests passing, 1 skipped** (the real-Google-Earth-Engine-connectivity test, which correctly skips when no live GCP service account is configured — see `SECURITY_REVIEW.md` / `CPANEL_DEPLOYMENT_GUIDE.md` for enabling it). 487 at v1.0's initial packaging, +4 permanent regression tests added by v1.1's tenant-isolation fix. v1.2 re-ran the identical 491/1 suite against a **freshly created PostgreSQL instance with no `postgis`/`pgcrypto` control files installed** — matching the reported production failure environment exactly — with zero regressions.
- Test types: unit (pure domain logic — formulas, aggregates, value objects, no I/O), integration (real PostgreSQL via `pgserver` in CI/validation, real HTTP via `TestClient`), and architecture (import-linter contracts: peer bounded-context independence, identity-as-shared-kernel, domain-layer purity, GIS/GEE libraries confined to Data Acquisition's infrastructure layer).
- Static analysis: `ruff check` clean, `mypy src/` clean (0 errors across 271 source files), `lint-imports` clean (4/4 contracts kept).
- **What test coverage does NOT claim**: these tests validate correctness of implemented logic against real infrastructure — they do not constitute a security penetration test, a load test, or a UAT sign-off from the tanzania NOVA-FIRAS/NOVA-WRRAS domain experts. See `SECURITY_REVIEW.md` for the security-specific audit.

## 3. Known Limitations (carried forward from each sprint's own documented scope decisions)

These are pre-existing, previously-documented design decisions from Sprints 1-14 — restated here for a deployment audience, not new findings:

- **No database-level Row-Level Security.** Tenant isolation is entirely application-layer (see `SECURITY_REVIEW.md` §3).
- **No real event/outbox relay.** Every domain event is written to `public.outbox_event` for audit purposes, but nothing consumes/relays it asynchronously yet — cross-context reactions (e.g., Notification's Early Warning Engine) are on-demand command invocations, not event subscribers, by design (documented in Sprint 11/12).
- **SMS notification channel is an honest stub** — `UnconfiguredSmsNotificationChannel` always reports "not implemented," no real SMS gateway (e.g. Twilio) has ever been integrated.
- **GEE/USGS/NASA/Copernicus require real credentials to do anything** — all four external data-acquisition integrations default to "not configured" and fail immediately/honestly rather than fabricating data. This is the correct behavior, but it means **Remote Sensing / external-provider acquisition features will not function until real credentials are supplied** (see `.env.production.example` / `CPANEL_DEPLOYMENT_GUIDE.md`).
- **SPEI (drought index) is a documented water-balance approximation**, not a full climatologically-fitted log-logistic-distribution SPEI — this platform stores no multi-decade historical climatology to fit one against (Sprint 14).
- **LST (land surface temperature) is only computed for Landsat** (the one supported source with a real thermal band in this pipeline) — honestly skipped, not approximated, for other sources.
- **No object storage integration** (`storage_backend`/`STORAGE_*` Settings exist since Sprint 0 but are not consumed by any context yet) — Local Upload's file bytes travel as base64 on the `AcquisitionJob` row itself, not in MinIO/S3.
- **No GDAL/rasterio** — all geometry math (Sprint 7) and remote-sensing feature extraction (Sprint 14) are pure Python operating on AOI-aggregate statistics, not per-pixel raster arrays.

## 4. Deployment Risks

| Risk | Likelihood on shared cPanel hosting | Mitigation |
|------|--------------------------------------|------------|
| Redis unavailable | **High** — many shared cPanel accounts have no Redis | **Fixed and verified (Sprint D)** — `/health/ready` now reports `200 degraded` (not `503`) when only Redis is down, and rate limiting silently falls back to an in-process counter; live-verified with Redis genuinely unreachable (`SPRINT_D_SECURITY_HARDENING_REPORT.md` §4) that registration/login/Analysis execution all continue to work |
| Passenger version too old for ASGI | Medium — depends on host's Passenger version | Use `startup.py` + reverse proxy fallback (see `CPANEL_DEPLOYMENT_GUIDE.md`) |
| Python version mismatch | Medium — cPanel's Python Selector may cap below 3.12 | `pyproject.toml` requires Python **3.12+** (the codebase uses `enum.StrEnum`/`datetime.UTC`/`typing.Self`, all 3.11+ features); confirm 3.12 is actually selectable before provisioning |
| No rate limiting on login | **Fixed and verified (Sprint D)** — see `SPRINT_D_SECURITY_HARDENING_REPORT.md` | Closed — application-layer rate limiting now covers login, registration, password reset, token refresh, analysis/prediction execution, and upload; still add reverse-proxy-level limiting as defense-in-depth |
| Tenant-isolation gap in Data Acquisition | **Fixed and verified** (see `SECURITY_RETEST_REPORT.md`); re-confirmed intact during Sprint D's security audit | Closed — no action needed |
| Migration chain fails on Postgres with no `postgis`/`pgcrypto` control files | **Fixed and verified** (see `MIGRATION_EXTENSION_FIX_REPORT.md`) — this is exactly what failed in the reported production deployment | Closed — no action needed; confirmed working against an extension-less PostgreSQL instance |
| Single PostgreSQL instance, no read replica/failover | Standard for a v1.0 launch | Ensure `CPANEL_DEPLOYMENT_GUIDE.md`'s backup procedure is actually scheduled (cron), not just documented |
| Unhandled-exception detail leakage | **Fixed and verified (Sprint D)** — see `SPRINT_D_SECURITY_HARDENING_REPORT.md` §1.3 | Closed — the catch-all handler now returns a safe generic message + traceId only; the real exception is still logged in full server-side |
| No access-token revocation | **Fixed and verified (Sprint D)** — see `SPRINT_D_SECURITY_HARDENING_REPORT.md` §1.1 | Closed — logout, password reset, suspend, deactivate, and an explicit "revoke all sessions" action all now genuinely invalidate previously-issued access tokens, not just refresh tokens |
| GEE/SMS/SMTP/USGS/NASA/Copernicus unconfigured | Expected at first launch | Confirm which integrations this deployment actually needs live on day one, and provision credentials for only those |

## 5. Recommendations

**Before launch:**
1. ~~Fix the tenant-isolation gap in `CatalogDatasetHandler`/`ScheduleAcquisitionJobHandler`~~ — **done**, see `SECURITY_RETEST_REPORT.md` (the one confirmed High-severity item; no remaining High findings block launch).
2. ~~Fix the migration chain aborting on PostgreSQL hosts without `postgis`/`pgcrypto` installed~~ — **done**, see `MIGRATION_EXTENSION_FIX_REPORT.md` (this was the actual cause of the reported production deployment failure).
3. Confirm `ENVIRONMENT=production` is set in the real `.env` — this is what activates the JWT-secret-default rejection guard.
4. Confirm Redis availability on the target cPanel account, or confirm `/health/ready`'s behavior if Redis is genuinely unavailable, before assuming the app degrades gracefully.
5. Add reverse-proxy-level rate limiting and request-body-size caps (both are Nginx/Apache config, not app code — see `CPANEL_DEPLOYMENT_GUIDE.md`).
6. Verify the exact Python version available via cPanel's Python Selector supports 3.12; if only 3.10/3.11 is available, re-run the full validation suite under that version before committing to it.

**Soon after launch (not blocking):**
7. Strip unhandled-exception detail from client-facing 500 responses (Low severity, contained fix).
8. Consider access-token revocation (denylist) if session-hijacking risk is a real concern for this deployment's threat model.
9. Schedule the backup cron job from `CPANEL_DEPLOYMENT_GUIDE.md` and verify a restore actually works, not just that the backup file is produced.

**This report makes no changes to business logic, formulas, or architecture** — it is an audit and packaging document only, per this deployment phase's explicit constraints. Findings that require a code fix are flagged for a follow-up change, not silently applied here.
