#!/usr/bin/env bash
# Entrypoint for the api service. Runs migrations are NOT applied here
# deliberately — `alembic upgrade head` is a separate, explicit step (CI's
# migration-check job, or an operator/deploy-pipeline action), never
# silently run as a side effect of starting the API process.
set -euo pipefail

RELOAD_FLAG=""
if [ "${ENVIRONMENT:-development}" = "development" ]; then
  RELOAD_FLAG="--reload"
fi

# Deployment-audit finding (docs/DEPLOYMENT_AUDIT_RENDER_RAILWAY_FLYIO.md §7):
# Railway assigns a dynamic port via $PORT and requires the process to bind
# to it; Render/Fly.io/docker-compose/cPanel do not set $PORT, so the
# ${PORT:-8000} fallback keeps every other existing deployment path
# byte-for-byte identical to before this change.
exec uvicorn georisk.api.app:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  ${RELOAD_FLAG}
