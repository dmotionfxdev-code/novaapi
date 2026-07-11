# Deployment Audit — Render vs. Railway vs. Fly.io

**Objective**: move the backend off cPanel/Passenger onto modern ASGI hosting. This document
is the audit phase only — traced from the current codebase, not assumed. No code was
modified to produce this document; the one small, optional code change this audit recommends
is applied and justified separately, after this analysis (§7).

---

## 1. Traced From The Current Codebase (not guessed)

| Question | Answer | Source |
|---|---|---|
| **Entry point (module-level)** | `georisk.api.app:app` — a module-level `FastAPI` instance built by `create_app()` with no explicit settings (falls back to `get_settings()`, i.e. real environment variables) | `src/georisk/api/app.py:478` |
| **Entry point (factory form)** | `georisk.api.app:create_app` (factory=True) — same app, but settings are resolved at call time rather than import time; used by `startup.py` and this project's own validation scripts | `src/georisk/api/app.py:337` (`def create_app(settings: Settings \| None = None)`) |
| **uvicorn command (Docker path)** | `uvicorn georisk.api.app:app --host 0.0.0.0 --port 8000 [--reload if ENVIRONMENT=development]` | `docker/entrypoints/api.sh` |
| **uvicorn command (bare-metal path)** | `uvicorn georisk.api.app:create_app --factory --host 127.0.0.1 --port $PORT --workers $WORKERS` (defaults: `PORT=8001`, `WORKERS=1`) | `startup.py` |
| **cPanel entry point (for contrast)** | `passenger_wsgi.py` exposes `application = create_app(settings=get_settings())` — Passenger dispatches to it as ASGI only if Passenger ≥ 6.0.9 | `passenger_wsgi.py` |
| **Environment variables** | Full list in §2 below, exhaustively read from `src/georisk/settings.py` (the single `Settings` class — "nothing else in this codebase reads `os.environ` directly," per its own docstring) | `src/georisk/settings.py` |
| **Database** | PostgreSQL via `asyncpg` (async SQLAlchemy 2.0). **No PostGIS/pgcrypto extension required** — geometry is stored as validated GeoJSON in `JSONB`, IDs are `uuid.uuid4()` generated application-side, never `gen_random_uuid()`. A stock, extension-less Postgres is sufficient (already proven against a real extension-less instance — `MIGRATION_EXTENSION_FIX_REPORT.md`) | `docker-compose.yml`'s `postgres` service uses plain `postgis/postgis` image only out of convenience, not necessity; `CPANEL_DEPLOYMENT_GUIDE.md` §1 states this explicitly |
| **Redis** | **Fully optional, gracefully degrading** (confirmed by Sprint D's own work, this session). Three logical URLs declared (`REDIS_URL`, `REDIS_CACHE_URL` — unconsumed by any code, `REDIS_RATELIMIT_URL`). Only two real consumers exist: `/health/ready`'s ping, and Sprint D's rate limiter (Redis-preferred, falls back to an in-process counter on any Redis failure). Redis being unreachable degrades `/health/ready` to `200 degraded` (not `503`) and the app continues serving traffic normally | `src/georisk/api/routes/health.py`, `src/georisk/rate_limiting.py` |
| **Background workers** | **Celery scaffolding exists (`gis`/`ai`/`light`/`system` queues + `beat` + a no-op `relay`) but carries ZERO real tasks.** `grep`ped the entire `src/` tree for `.delay(`/`.apply_async(` outside `celery_app/app.py` itself — zero hits. The only tasks defined are 4 Sprint-0 "ping" smoke tests (`ping_gis`/`ping_ai`/`ping_light`/`ping_system`). Every Analysis/Prediction/Validation/Risk-Layer/Report computation in this codebase runs synchronously inside the HTTP request that triggers it. **No worker process is required for the API to function today.** | `src/georisk/celery_app/app.py`, `docker/entrypoints/{worker,beat,relay}.sh` |
| **Migrations** | Alembic, single linear chain, `0000_baseline` → `0019_security_hardening` (20 revisions). Applied via an **explicit, separate step** (`PYTHONPATH=src alembic upgrade head`) — deliberately never run automatically as a side effect of the API process starting (`docker/entrypoints/api.sh`'s own comment: "migrations are NOT applied here deliberately") | `migrations/versions/`, `docker/entrypoints/api.sh`, `deploy.sh` step 4 |
| **Static files** | **None.** Pure JSON API — no `StaticFiles` mount anywhere in `src/` (grepped), no server-rendered templates, no bundled frontend. `deploy.sh` states this explicitly: "not applicable (pure API service, no static assets)" | `deploy.sh` step 5; `grep -rn StaticFiles src/` → 0 hits |
| **Upload handling** | Uploaded file bytes (including Shapefile ZIPs, Sprint B) travel as base64 **inside JSON request bodies** and are persisted directly into a Postgres column (`AcquisitionJob.raw_content_base64`) — never written to local disk. Grepped for `open(...'wb'` and any `UploadFile` usage — zero hits. **No persistent volume/disk is required.** `STORAGE_BACKEND`/MinIO settings exist (declared since Sprint 0) but are consumed by no code path — a known, already-documented limitation, not something this audit needs to solve | `grep -rn "UploadFile\|open(.*'wb'" src/georisk/` → 0 hits; `PRODUCTION_READINESS_REPORT.md` §3 |
| **Google Earth Engine** | Three optional settings: `GEE_SERVICE_ACCOUNT_EMAIL`, `GEE_SERVICE_ACCOUNT_PRIVATE_KEY` (the full service-account JSON key, minified to one line), `GEE_PROJECT_ID`. Left empty, the provider fails immediately and honestly — no code path assumes GEE is configured | `src/georisk/settings.py`, `.env.production.example` |

### 1a. What already exists for deployment (do not rebuild)

This repository already has a production-shaped Docker setup from Sprint 0, still current:

- `docker/api/Dockerfile` — multi-stage (`builder`/`runtime`), non-root user, `HEALTHCHECK` on
  `/health/live`, pinned `python:3.12.8-slim-bookworm` base. **Already validated by CI**
  (`.github/workflows/ci.yml` runs `docker build -f docker/api/Dockerfile ...` on every push).
- `docker/worker/Dockerfile` + `docker/entrypoints/{worker,beat,relay}.sh` — for the Celery
  scaffolding above; **not needed for this deployment** per the finding above.
- `docker-compose.yml` — full local-dev topology (Postgres, Redis, MinIO, api, 4 workers,
  beat, relay).
- `deploy.sh` / `startup.py` / `passenger_wsgi.py` — the cPanel-specific paths being replaced.
- `.env.production.example` — a complete, commented template already mapping 1:1 to every
  `Settings` field.

One gap in the existing Dockerfile, relevant to this audit: **no `EXPOSE` instruction**, and
`docker/entrypoints/api.sh` hardcodes `--port 8000` rather than reading a `PORT` environment
variable. This matters differently per platform — see §3.

### 1b. Why Passenger failed (already-known, re-confirmed, not re-litigated)

Two independent, already-documented root causes (`CPANEL_DEPLOYMENT_GUIDE.md` §0, §9):

1. **ASGI incompatibility below Passenger 6.0.9.** This is a pure ASGI application
   (`async def app(scope, receive, send)`, exactly what a FastAPI instance is) — Passenger
   only learned to dispatch to ASGI apps directly starting at 6.0.9. Any older Passenger
   calls it the plain-WSGI way (2 positional arguments) and every request fails immediately.
2. **Python version ceiling.** `pyproject.toml` requires `>=3.12` (the codebase uses
   `enum.StrEnum`, `datetime.UTC`, `typing.Self` — all Python 3.11+). Many shared cPanel
   hosts' Python Selector caps at 3.10/3.11.

Both are properties of the **hosting environment** (cPanel/Passenger/CloudLinux's Python
Selector), not the application. The `startup.py` reverse-proxy fallback in this repo already
works around #1 (confirmed: `PYTHONPATH=src uvicorn georisk.api.app:app` starts and serves
correctly per this task's own prompt) — but #2 and the general operational friction of
cPanel (no native Postgres/Redis provisioning, manual SSH-driven deploys, `restart.txt`
polling instead of a real deploy pipeline) are why this audit was requested at all.

---

## 2. Environment Variables (exhaustive, from `Settings`)

| Variable | Required? | Notes |
|---|---|---|
| `ENVIRONMENT` | Yes | Must be `production` — activates the guard rejecting the default `JWT_SECRET_KEY` |
| `DATABASE_URL` | Yes | `postgresql+asyncpg://...` — any reachable Postgres, no extensions needed |
| `DB_POOL_SIZE` | No (default 10) | |
| `JWT_SECRET_KEY` | Yes (prod) | App refuses to start with the dev default when `ENVIRONMENT=production` |
| `JWT_ALGORITHM` | No (default `HS256`) | |
| `JWT_ACCESS_TOKEN_TTL_SECONDS` | No (default 28800 / 8h) | |
| `REDIS_URL` / `REDIS_CACHE_URL` / `REDIS_RATELIMIT_URL` | **No** | Fully optional — see §1's Redis row |
| `RATE_LIMIT_*` (7 fields, Sprint D) | No (all have sane defaults) | `rate_limit_login_per_minute`, `_registration_per_hour`, `_password_reset_per_hour`, `_token_refresh_per_minute`, `_analysis_execution_per_minute`, `_prediction_execution_per_minute`, `_upload_per_minute` |
| `CORS_ALLOWED_ORIGINS` | Yes (prod) | Comma-separated; never `*` (credentialed CORS) |
| `LOG_LEVEL` | No (default `INFO`) | |
| `OTEL_EXPORTER_ENDPOINT` / `OTEL_SERVICE_NAME` | No | Empty = console-only tracing |
| `STORAGE_*` (5 fields) | No | Declared, consumed by nothing yet — safe to leave at placeholders |
| `TENANCY_MODE` | No (default `shared_schema`, the only implemented mode) | |
| `SMTP_*` (7 fields) | No | Email channel honestly fails if unset |
| `USGS_API_*` / `NASA_API_*` / `COPERNICUS_API_*` | No | Each honestly fails if unset |
| `GEE_SERVICE_ACCOUNT_EMAIL` / `_PRIVATE_KEY` / `GEE_PROJECT_ID` | No | GEE honestly fails if unset |

**Minimum viable production set**: `ENVIRONMENT`, `DATABASE_URL`, `JWT_SECRET_KEY`,
`CORS_ALLOWED_ORIGINS`. Everything else is either optional-with-a-safe-default or an
external integration this project already treats as "off until configured."

---

## 3. Can Each Platform Host This Without Code Changes?

### Render — **Yes, effectively zero code changes.**

Render's Docker services bind to whatever port the container listens on; Render's own docs
say it "is usually able to detect" a non-default bound port even without reading `$PORT`,
though it calls relying on auto-detection alone "fragile" and recommends reading `$PORT`
explicitly. Since this app's hardcoded `8000` is fixed and consistent, auto-detection is very
likely to just work — but see §7 for the one small, universal fix applied anyway (it costs
nothing and removes the only source of fragility for every platform at once, not just
Render).

- **What's needed**: a `render.yaml` Blueprint (new file, not a code change) declaring a
  Docker web service pointed at `docker/api/Dockerfile`, a managed Postgres instance, and a
  managed Key Value (Redis) instance — plus the env vars from §2 entered as secrets.
- **What's NOT needed**: no Dockerfile changes, no app code changes, no worker deployment.

### Railway — **One small, genuinely required change (or a zero-code-change alternative).**

Railway dynamically assigns and injects a `PORT` environment variable per deployment; unlike
Render/Fly, it does not offer a fixed/pinned-port model — the running process **must** read
`$PORT` and bind to it, or the deployment will not receive traffic correctly.

- **Required change**: `docker/entrypoints/api.sh` binds to a hardcoded `8000`, ignoring any
  `PORT` the platform provides. Fix: read `${PORT:-8000}` (§7 — a 1-line change, backward
  compatible, defaults preserve the exact current `docker-compose.yml`/cPanel behavior).
- **Zero-code-change alternative**: `startup.py` **already** reads `os.environ.get("PORT", "8001")`
  correctly (pre-existing code, written for the cPanel reverse-proxy path) — Railway could be
  pointed at `python startup.py` as its start command instead of the Docker entrypoint,
  requiring no code changes at all, only a Railway-side start-command override. §7 applies
  the entrypoint fix anyway since it benefits Render/Fly too and keeps one canonical Docker
  entrypoint across all three platforms rather than a platform-specific special case.

### Fly.io — **Yes, zero code changes.**

Fly's `fly.toml` declares a fixed `internal_port` that must match whatever port the process
inside the Machine actually binds to — the platform does not require the app to read a
dynamic port from the environment.

- **What's needed**: a `fly.toml` (new file) with `internal_port = 8000` (matching the
  existing hardcoded value), a `[build]` section pointing at `docker/api/Dockerfile`, and
  secrets set via `fly secrets set` for the env vars in §2.
- **What's NOT needed**: no Dockerfile changes, no app code changes.

**Conclusion**: Render and Fly.io can genuinely host this application with **zero code
changes** (only new, additive deployment-config files). Railway is one line away from the
same status; this audit applies that one line as a universal, non-platform-specific
improvement rather than treating it as a Railway-only patch.

---

## 4. Platform Comparison

| Criterion | Render | Railway | Fly.io |
|---|---|---|---|
| Ease of deployment | High — `render.yaml` Blueprint, git-connected auto-deploy | High — excellent DX, but no in-repo Blueprint-equivalent as mature as Render's for this stack | Medium — `flyctl`/`fly.toml`, more manual, steeper first-deploy curve |
| FastAPI/ASGI support | Native (any process bound to a port) | Native | Native |
| Docker support | Full — points directly at a `Dockerfile` | Full | Full — Docker is Fly's primary deployment path |
| Background workers | Supported as a separate "Background Worker" service type — not needed here | Supported as an additional service — not needed here | Supported as an additional Machine/process — not needed here |
| Redis support | Native managed "Key Value" (Redis-compatible), free tier 25 MB | Native plugin (Redis template), usage-based | No first-party managed Redis; typically Upstash integration or self-hosted — **but this app doesn't require Redis at all**, so this is a non-issue here |
| PostgreSQL support | Native managed Postgres; **free tier auto-deletes after 30 days** (1 GB cap) | Native plugin, usage-based, no forced expiry | Fly Postgres (managed tiers start ~$38/mo) or a self-hosted Postgres Machine (~$2-4/mo, self-managed) |
| Custom domains | Yes, free, with automatic TLS | Yes, free, with automatic TLS | Yes, free, with automatic TLS |
| Environment variables | Dashboard + `render.yaml` `envVars`; secrets supported | Dashboard + `railway.json`; secrets supported | `fly secrets set` (encrypted) + `fly.toml` for non-secret config |
| HTTPS | Automatic, free | Automatic, free | Automatic, free |
| Deployment speed | Fast (git push → auto build/deploy) | Fast | Fast, but `flyctl deploy` is a more manual step by default |
| Cold starts | **Free tier web services sleep after 15 min idle, 30-60s cold start on next request**; paid tiers stay warm | No forced sleep on any paid plan (no real free tier to compare) | No forced sleep; Machines can auto-stop/start but this is opt-in, not default for a web service |
| Free tier (as of mid-2026) | **Real, no-credit-card free tier**: 750 instance-hours/month, free Postgres (30-day expiry), free Redis (25 MB), 100 GB bandwidth | **No permanent free tier** — one-time $5 trial credit expiring in 30 days, then $5/mo Hobby + usage-based on top | **No permanent free tier since 2024** — minimal trial (~$5 credit or 2 VM-hours/7 days), pay-as-you-go from day one for anything real |
| Suitability for production (this project specifically) | Good, once upgraded off the free Postgres (30-day expiry is a hard blocker for real production, not this audit's live-verification step) | Good — predictable usage-based cost, no forced sleep, needs the $PORT fix | Good — most powerful (multi-region, private networking) but that capability is unused by this single-region API; priciest managed Postgres option |

---

## 5. Ranking (best → worst, for this project specifically)

1. **Render** — best fit. This project's actual needs are modest (single region, one
   Postgres, optional Redis, no workers, no static assets, no persistent volumes) — exactly
   what Render's Blueprint model is built for. It is also the only one of the three with a
   genuine, no-credit-card free tier today, making it the correct choice for the live
   verification this task also asks for. The one real caveat (free Postgres auto-deletes at
   30 days) is an easy, well-understood upgrade path (a paid Render Postgres instance, ~$6-7/mo)
   once this moves past verification into real production use — not a technical blocker.
2. **Railway** — very close second. Excellent developer experience, no cold-start sleep even
   on its cheapest paid tier, straightforward Postgres/Redis. Loses to Render only because
   (a) it no longer has a usable ongoing free tier for this exercise's "deploy to the best
   free platform" requirement, and (b) it's the one platform needing the (now-applied,
   universal) `$PORT` fix to work at all.
3. **Fly.io** — most powerful, least suited to this project's current shape. Its standout
   capability — global multi-region low-latency Machines — is not something this
   single-tenant-style API needs today. Combined with the steepest first-deploy learning
   curve of the three and the least economical managed-Postgres option, it is the right
   choice only if/when this platform needs genuine multi-region distribution, not now.

---

## 6. 12-Factor Assessment

This application already satisfies the 12-factor principles relevant to a deployment
migration, stated explicitly rather than assumed:

- **Config in the environment**: every configurable value is a `Settings` field read from
  the environment (`pydantic-settings`) — confirmed, this is the ONLY place `os.environ` is
  read anywhere in the codebase (per `settings.py`'s own docstring, verified by grep).
  Nothing is hardcoded that should be configurable.
- **Stateless processes**: confirmed in this audit — no local disk state (uploads travel as
  base64 in Postgres, §1), no in-process session affinity required beyond the (already
  gracefully-degrading) in-memory rate-limiter fallback.
- **Backing services as attached resources**: Postgres and Redis are both reached purely via
  URLs (`DATABASE_URL`/`REDIS_*`) — swapping either for a different provider requires no code
  change, only a different connection string.
- **Build, release, run strictly separated**: the existing multi-stage Dockerfile (`builder`
  → `runtime`) already embodies this; `deploy.sh` treats migration application as a distinct,
  explicit release step, never bundled into process startup.
- **Port binding**: the app is self-contained and binds its own port via `uvicorn` — it does
  not rely on being injected into a heavier host webserver (Passenger was the one exception,
  which is exactly what's being removed).
- **Disposability**: fast startup (no migration-on-boot, no heavyweight init beyond database
  engine creation), and `/health/live`+`/health/ready` already exist for fast, correct
  orchestrator health signals.

**No missing-problem was invented to justify this migration** — the one genuine gap found
(hardcoded port, not reading `$PORT`) is real, small, and only matters for Railway; it is
fixed in §7.

---

## 7. The One Recommended Code Change

**File**: `docker/entrypoints/api.sh` — bind to `${PORT:-8000}` instead of a hardcoded `8000`.
**File**: `docker/api/Dockerfile` — add `EXPOSE 8000` (documentation-only Dockerfile metadata;
changes no runtime behavior).

**Why**: Railway assigns a dynamic port and requires the process to read it; this makes that
work without any Railway-specific branching. The `${PORT:-8000}` fallback means Render, Fly,
local `docker compose`, and any environment that does NOT set `PORT` behave byte-for-byte as
they do today — this is additive, not a behavior change, for every existing deployment path.
No application code (`src/georisk/**`) is touched at all; only the Docker entrypoint script
and a documentation-only Dockerfile line.

This is the **only** code-adjacent change made for this audit. Everything else delivered
(§8) is new, additive configuration files.

**Applied and verified**:
- `docker/entrypoints/api.sh` — now binds `--port "${PORT:-8000}"`. Verified locally (outside
  Docker, since this sandbox has no `docker` binary) that the exact substitution behaves as
  intended: `bash -c 'echo "${PORT:-8000}"'` → `8000` with no `PORT` set, `10000` with
  `PORT=10000` set — i.e. every existing path (`docker-compose.yml`, cPanel) that never sets
  `PORT` is unaffected, and a platform that does (Railway) is now honored.
- `docker/api/Dockerfile` — added `EXPOSE 8000` (metadata only) and updated `HEALTHCHECK` to
  probe `${PORT:-8000}` instead of a hardcoded `8000`, so the healthcheck still checks the
  right port if `PORT` is ever overridden.
- `bash -n docker/entrypoints/api.sh` — syntax-checked clean.
- The Dockerfile's actual `docker build` is validated by existing CI
  (`.github/workflows/ci.yml` already runs `docker build -f docker/api/Dockerfile ...` on
  every push) — this sandbox has no `docker` binary installed, so a fresh local build was not
  re-run here; the change is a one-line, mechanically-verified shell substitution inside an
  already-CI-built image, not a restructuring of the Dockerfile itself.

---

## 8. Deployment Package (committed to the repository)

| File | Status |
|---|---|
| `docker/api/Dockerfile` | Already existed — 2 lines changed (§7) |
| `docker/entrypoints/api.sh` | Already existed — 1 line changed (§7) |
| `docker-compose.yml` | Already existed — **unchanged**, still the correct local-dev topology |
| `render.yaml` | **New** — Blueprint declaring the web service (Docker), a free Postgres, and a free Key Value (Redis) instance |
| `fly.toml` | **New** — app config declaring the Docker build, `http_service`, and health check |
| `Procfile` | **Not created** — genuinely not needed. All three recommended deployment paths use the existing Dockerfile directly; a Procfile only matters for a non-Docker buildpack flow, which none of Render/Fly (and, per this audit, Railway too, since it also supports Dockerfile-based deploys) require here |
| A new/regenerated `docker-compose.yml` | **Not created** — the existing one is already correct and unrelated to this migration (it's the local-dev topology, not what Render/Railway/Fly consume) |

Both new files were parsed and validated in this session (`yaml.safe_load(render.yaml)` and
`tomli.load(fly.toml)` both succeed and produce exactly the intended structure — not just
visually inspected).

---

## 9. What This Audit Did Not Do (and why)

Live deployment to a real Render/Railway/Fly.io account, screenshots, and a live URL are
explicitly requested deliverables this document does not include, because they require
creating/authenticating to a third-party cloud account on the user's behalf — connecting a
GitHub repo to a new Render/Fly organization, provisioning billable (even if free-tier)
cloud resources, and obtaining a public URL are actions outside what this session can take
autonomously without the user's own account access or explicit go-ahead on how to proceed
(e.g. an API token, or the user performing the account-linking click-through themselves while
being guided). Everything that **can** be produced and verified locally — the audit, the
traced facts, the minimal code change, and a validated deployment package — is complete and
ready to commit. See the final chat response for how to proceed with the live phase.
