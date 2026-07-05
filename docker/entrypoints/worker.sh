#!/usr/bin/env bash
# Entrypoint for every worker-* service (gis / ai / light / system).
#
# Sprint 0 Review finding #1 / Remediation #1 (Critical): this script takes
# the queue name as its SOLE argument. docker-compose.yml's worker service
# `command:` entries MUST pass exactly one token (e.g. `["gis"]`), never a
# two-token `["worker", "gis"]` — that mismatch was the original defect:
# `$1` would have received "worker" instead of the intended queue name, and
# no worker would have bound to the correct queue.
set -euo pipefail

QUEUE="${1:?queue name required: gis|ai|light|system}"
CELERY_NODE_NAME="${QUEUE}@$(hostname)"

# HEALTHCHECK (docker/worker/Dockerfile) runs as a separate process spawned
# fresh by the Docker daemon — it does NOT inherit a plain `export` made by
# this script's shell session. Write the node name to a file instead, which
# the healthcheck reads back at check time. (This is a corrected version of
# an initial draft that tried to pass it via an exported env var, which
# would have silently produced an always-empty `-d ""` target.)
echo -n "${CELERY_NODE_NAME}" > /tmp/celery_node_name

exec celery -A georisk.celery_app.app worker \
  -Q "${QUEUE}" \
  -n "${CELERY_NODE_NAME}" \
  --loglevel=info
