# syntax=docker/dockerfile:1
#
# Same base/runtime split and hardening as docker/api/Dockerfile (Sprint 0
# Review finding #12 / Remediation #12 — this file was referenced but never
# shown in the original bootstrap draft; it now exists and follows the
# identical pattern). Used for worker-gis / worker-ai / worker-light /
# worker-system / relay / beat — the queue (or role) is selected at
# container-start time via `command:` in docker-compose.yml, not baked in
# here, per Implementation Bootstrap §7's "one image, role-based
# entrypoints" decision.

FROM python:3.12.8-slim-bookworm AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

FROM base AS builder

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[dev]"

FROM base AS runtime

RUN groupadd --system georisk \
    && useradd --system --gid georisk --home-dir /app --shell /usr/sbin/nologin georisk

COPY pyproject.toml README.md ./
COPY src/ ./src/
COPY migrations/ ./migrations/
COPY alembic.ini ./
COPY docker/entrypoints/ ./entrypoints/

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e "."

RUN chmod +x ./entrypoints/*.sh \
    && chown -R georisk:georisk /app

RUN gdalinfo --formats | grep -qi "GTiff" \
    || (echo "FATAL: GDAL build is missing GeoTIFF/COG driver support" && exit 1)

USER georisk

# Generic Celery liveness check: pings the specific node this container
# started rather than `inspect ping` with no target, which would report
# this container healthy based on any OTHER worker's response reachable via
# the same broker. The node name is read from the file entrypoints/worker.sh
# writes at start time (not an env var — HEALTHCHECK runs as a fresh process
# that does not inherit a plain shell `export` from the entrypoint script).
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
    CMD celery -A georisk.celery_app.app inspect ping -d "$(cat /tmp/celery_node_name)" --timeout 5 || exit 1

ENTRYPOINT ["./entrypoints/worker.sh"]
