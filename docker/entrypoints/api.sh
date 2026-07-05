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

exec uvicorn georisk.api.app:app \
  --host 0.0.0.0 \
  --port 8000 \
  ${RELOAD_FLAG}
