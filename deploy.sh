#!/usr/bin/env bash
# NOVA GeoRisk Platform — production deployment script.
#
# Intended to be run from the application root on the cPanel server (via
# SSH, or cPanel's "Terminal" app) AFTER the Python Application has been
# created in cPanel's Python Application Manager (which provisions the
# virtualenv this script activates). See CPANEL_DEPLOYMENT_GUIDE.md for
# the one-time setup steps this script does NOT do (creating the
# PostgreSQL database/user, creating the cPanel Python App itself,
# domain/SSL setup).
#
# Usage:
#   ./deploy.sh                 # install deps + migrate + health check
#   ./deploy.sh --skip-install  # migrate + health check only (faster
#                                # redeploys where dependencies haven't changed)
#   ./deploy.sh --no-health-check
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

SKIP_INSTALL=false
RUN_HEALTH_CHECK=true
for arg in "$@"; do
  case "$arg" in
    --skip-install) SKIP_INSTALL=true ;;
    --no-health-check) RUN_HEALTH_CHECK=false ;;
    *) echo "Unknown argument: $arg" >&2; exit 1 ;;
  esac
done

# cPanel's Python Application Manager creates a virtualenv and exposes an
# activation script at this conventional path; `PYTHON_VENV` can be
# overridden if your cPanel account's virtualenv lives elsewhere (check
# the "Setup Python App" page for the exact path — it is shown there).
PYTHON_VENV="${PYTHON_VENV:-$HOME/virtualenv/$(basename "$PROJECT_ROOT")/*/bin/activate}"

log() { echo "[deploy] $*"; }

# --- 1. Activate the cPanel-managed virtualenv ---
activate_candidates=($PYTHON_VENV)
if [ -f "${activate_candidates[0]:-}" ]; then
  log "Activating virtualenv: ${activate_candidates[0]}"
  # shellcheck disable=SC1090
  source "${activate_candidates[0]}"
else
  log "WARNING: could not find a cPanel virtualenv activate script at" \
      "'$PYTHON_VENV'. Falling back to whatever 'python3'/'pip' resolve to" \
      "on PATH — this is only correct if you have already activated the" \
      "right environment yourself."
fi

# --- 2. Verify required environment is present before doing anything else ---
if [ ! -f "$PROJECT_ROOT/.env" ]; then
  log "ERROR: .env not found at $PROJECT_ROOT/.env — copy .env.production.example" \
      "to .env and fill in real values before deploying. Aborting."
  exit 1
fi

# shellcheck disable=SC1091
set -a; source "$PROJECT_ROOT/.env"; set +a

if [ "${ENVIRONMENT:-}" != "production" ]; then
  log "WARNING: ENVIRONMENT is '${ENVIRONMENT:-<unset>}', not 'production'." \
      "The app will refuse to start if JWT_SECRET_KEY is still the dev default" \
      "ONLY when ENVIRONMENT=production — double check this is intentional."
fi

# --- 3. Install dependencies ---
if [ "$SKIP_INSTALL" = false ]; then
  log "Installing dependencies from requirements.txt ..."
  pip install --upgrade pip
  pip install -r requirements.txt
else
  log "Skipping dependency installation (--skip-install)."
fi

# --- 4. Run database migrations ---
log "Running Alembic migrations (0000 -> head) ..."
PYTHONPATH="$PROJECT_ROOT/src" alembic upgrade head
log "Migrations applied successfully."

# --- 5. Collect static assets ---
# N/A: NOVA GeoRisk Platform is a pure JSON API (FastAPI/Starlette) with no
# server-rendered templates or bundled frontend assets — there is nothing
# to collect. This step is intentionally a no-op, not omitted by oversight.
log "Static asset collection: not applicable (pure API service, no static assets)."

# --- 6. Restart the application process ---
# cPanel's Python Application Manager restarts the app when its "restart"
# file is touched (Passenger convention) — this works for both the
# passenger_wsgi.py path and cPanel-managed process supervision.
RESTART_FILE="$PROJECT_ROOT/tmp/restart.txt"
mkdir -p "$PROJECT_ROOT/tmp"
touch "$RESTART_FILE"
log "Touched $RESTART_FILE to signal Passenger to restart the app."
log "If running via startup.py/uvicorn instead (see CPANEL_DEPLOYMENT_GUIDE.md's" \
    "reverse-proxy alternative), restart that process manually now" \
    "(e.g. 'supervisorctl restart georisk-api')."

# --- 7. Health check ---
if [ "$RUN_HEALTH_CHECK" = true ]; then
  log "Waiting for the app to come back up before health-checking ..."
  sleep 5
  HEALTH_URL="${HEALTH_CHECK_URL:-https://novaapi.novarex.co.tz/health/ready}"
  log "Checking $HEALTH_URL ..."
  # NOTE: do not fall back to a literal "000" on curl failure here — curl
  # itself already writes "000" via -w when it gets no parseable HTTP
  # status (connection refused, TLS failure, timeout, etc.), so an
  # `|| echo "000"` on top of that double-prints as "000000" and hides
  # which of the two actually happened. Capture curl's own exit code
  # separately instead, so a connection-level failure and a real-but-bad
  # HTTP status are never confused with each other in the log.
  set +e
  http_status=$(curl -s -o /tmp/georisk_health_check_body.json -w "%{http_code}" \
    --max-time 15 "$HEALTH_URL")
  curl_exit=$?
  set -e
  if [ "$curl_exit" -ne 0 ]; then
    log "Health check FAILED — curl could not complete the request at all" \
        "(exit code $curl_exit: connection refused, DNS failure, TLS error, or timeout —" \
        "see 'man curl' exit codes). This means the app never even got a chance to" \
        "respond; check the reverse proxy / Passenger layer, not the app itself."
    log "Deployment completed but the app is NOT confirmed healthy — investigate" \
        "before considering this deploy successful."
    exit 1
  elif [ "$http_status" = "200" ]; then
    log "Health check PASSED (HTTP 200)."
    cat /tmp/georisk_health_check_body.json
  else
    log "Health check FAILED (HTTP $http_status). Response body:"
    cat /tmp/georisk_health_check_body.json 2>/dev/null || true
    log "Deployment completed but the app is NOT confirmed healthy — investigate" \
        "before considering this deploy successful."
    exit 1
  fi
else
  log "Skipping health check (--no-health-check)."
fi

log "Deployment complete."
