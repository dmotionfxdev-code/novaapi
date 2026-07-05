#!/usr/bin/env bash
# Nightly PostgreSQL backup for NOVA GeoRisk Platform's production database.
# Referenced by CPANEL_DEPLOYMENT_GUIDE.md §11 — intended to run via cron,
# not as part of the application's own request-serving code path.
#
# Usage: ./scripts/backup_db.sh
# Requires: DATABASE_URL in .env (asyncpg scheme is stripped automatically
# below since `pg_dump` needs the plain `postgresql://` scheme).
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
set -a; source "$PROJECT_ROOT/.env"; set +a

if [ -z "${DATABASE_URL:-}" ]; then
  echo "DATABASE_URL not set in .env — aborting backup." >&2
  exit 1
fi

PLAIN_DATABASE_URL="${DATABASE_URL/postgresql+asyncpg:/postgresql:}"

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/georisk}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "$BACKUP_DIR"

echo "[backup] Dumping database to $BACKUP_DIR/georisk_${TIMESTAMP}.dump ..."
pg_dump "$PLAIN_DATABASE_URL" --format=custom --file="$BACKUP_DIR/georisk_${TIMESTAMP}.dump"

echo "[backup] Pruning backups older than $RETENTION_DAYS days ..."
find "$BACKUP_DIR" -name "georisk_*.dump" -mtime "+$RETENTION_DAYS" -delete

echo "[backup] Done: georisk_${TIMESTAMP}.dump"
