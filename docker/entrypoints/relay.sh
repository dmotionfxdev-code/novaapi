#!/usr/bin/env bash
# Entrypoint for the outbox relay process (Infrastructure Architecture §9).
#
# No relay implementation exists in Sprint 0 — there is no outbox table
# consumer to run yet (Roadmap Sprint 3 introduces it). This script exists
# so the `relay` service's deployment topology (docker-compose.yml) is
# proven startable now, against a no-op, rather than being an unverified
# gap discovered when Sprint 3 needs it.
set -euo pipefail

echo "[relay] no-op in Sprint 0 — outbox relay lands in Roadmap Sprint 3 (Infrastructure Architecture §9)."
echo "[relay] sleeping to keep the service topology alive for docker compose health checks."
while true; do
  sleep 3600
done
