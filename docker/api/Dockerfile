# syntax=docker/dockerfile:1
#
# Sprint 0 Review / Remediation Plan fixes applied in this file:
#   #2  (Critical) non-root USER in the runtime stage
#   #9  (High)     base image pinned to an explicit patch + Debian codename,
#                   not the floating `python:3.12-slim` tag — see note below
#                   on why this is not pinned to a sha256 digest yet
#   #21 (Medium)   dev/test tooling (pytest, mypy, ruff, ...) is installed
#                   only in the `builder` stage, never in `runtime`
#   #24 (Medium)   HEALTHCHECK instruction, keyed to /health/live
#   #34 (Low)      build fails if the GDAL install lacks GeoTIFF/COG support
#
# NOTE on base-image pinning: Remediation #9 recommends pinning to a
# resolved sha256 digest. That digest cannot be safely fabricated in a
# design/review document — an invented digest would make every build fail
# outright, which is worse than a floating tag. Pin to a digest as the next
# concrete step, obtained from a machine with registry access:
#     docker pull python:3.12.8-slim-bookworm
#     docker inspect --format='{{index .RepoDigests 0}}' python:3.12.8-slim-bookworm
# then replace the FROM line below with `python:3.12.8-slim-bookworm@sha256:<digest>`.

FROM python:3.12.8-slim-bookworm AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev build-essential curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- builder: full dependency set (including dev/test tooling) -----------
FROM base AS builder

COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[dev]"

# --- runtime: production dependency set only, no dev/test tooling --------
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

# Sprint 0 Review finding #34 / Remediation #34 — fail the build itself,
# not Roadmap Sprint 9, if this base image's GDAL lacks the format driver
# the GeoTIFF/COG pipeline (Infrastructure Architecture §15) depends on.
RUN gdalinfo --formats | grep -qi "GTiff" \
    || (echo "FATAL: GDAL build is missing GeoTIFF/COG driver support" && exit 1)

USER georisk

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
    CMD curl -f http://localhost:8000/health/live || exit 1

ENTRYPOINT ["./entrypoints/api.sh"]
