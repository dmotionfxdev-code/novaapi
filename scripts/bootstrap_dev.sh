#!/usr/bin/env bash
# One-shot local dev bootstrap: copies the env template, brings up the
# infrastructure services, waits for them, then runs migrations.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit it if your local setup needs different values."
fi

docker compose up -d postgres redis minio
python3 scripts/wait_for_services.py

echo "Running migrations..."
alembic upgrade head

echo "Done. Start the full stack with: docker compose up"
