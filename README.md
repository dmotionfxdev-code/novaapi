# NOVA GeoRisk Platform

Assessment-centric, workflow-driven, multi-hazard risk intelligence platform (FIRAS / WRRAS / LRAS / DIRAS as workflow templates and hazard strategies on one platform — see `docs/architecture/GEORISK_PLATFORM_ARCHITECTURE.md`).

This repository is Sprint 0 of the [Implementation Roadmap](../docs/architecture/GEORISK_IMPLEMENTATION_ROADMAP.md): platform foundation only. **No business logic, no hazard calculations, no domain API routes exist yet.** See `docs/architecture/` for the full design record — architecture, domain model, application layer, API resource model, infrastructure architecture, platform architecture, roadmap, gap analysis, bootstrap spec, design review, and remediation plan.

## What's here

- A FastAPI application skeleton with one route (`/health/live`, `/health/ready`).
- SQLAlchemy 2.0 async engine/session plumbing, no domain models.
- Alembic wired to PostGIS, with an empty baseline migration (extensions + logical schemas only).
- Celery configured with four queues (`gis`, `ai`, `light`, `system`), no real tasks — only smoke tests.
- Structured JSON logging with trace-id correlation.
- RFC 7807 error-handling middleware, with a domain-exception base hierarchy.
- CI: lint, typecheck, import-boundary enforcement, tests, migration up/down check, dependency and image vulnerability scanning, Docker build.

## Quick start

```bash
cp .env.example .env
make up
# in another terminal:
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

## Repository layout

See `docs/architecture/GEORISK_IMPLEMENTATION_BOOTSTRAP.md` §1–2 for the full rationale. In brief:

```
src/georisk/
├── shared_kernel/     # typed IDs, domain exception hierarchy — imported by every context
├── contexts/          # one folder per bounded context; empty until its sprint lands
├── db/                # SQLAlchemy base, session management, logical schema names
├── celery_app/        # Celery app, queue routing, base task class
├── observability/     # structured logging, tracing
└── api/               # FastAPI app factory, middleware, routes
```

Every empty `contexts/<name>/` folder carries a `README.md` stating which Roadmap sprint populates it — see that file before assuming a directory is dead weight.

## Development

```bash
pip install -e ".[dev]"
pre-commit install
make lint typecheck import-lint test
```

## Regenerating the dependency lock

```bash
pip install pip-tools
make lock
```

CI fails if the committed lock is out of sync with `pyproject.toml` (Sprint 0 Remediation Plan, finding #3). The lockfiles currently committed were generated on Python 3.10 (the only interpreter available in the environment this repository was bootstrapped in) rather than the project's actual target of 3.12+. CI's `lockfile-check` job runs on 3.12 and is the authoritative check — if it reports drift on the first run against these files, regenerate both locks on 3.12 (`make lock`) and commit the result; that resolved version pinning is what every other job then installs from.
