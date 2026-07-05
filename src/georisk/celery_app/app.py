"""Celery application: four queues (gis / ai / light / system), matching
Application Layer §7 and Infrastructure Architecture §11's workload-profile
segmentation — a heavy `gis` backlog during a disaster-response burst must
never delay report generation or notification delivery for other tenants.

Routing is centralized in ``task_routes`` (Sprint 0 Review finding #15 /
Remediation #15) — never scattered across per-task ``queue=`` kwargs — so
routing intent is auditable in one place as real tasks accumulate from
Roadmap Sprint 3 onward.
"""

from __future__ import annotations

import logging

from celery import Celery
from celery.signals import worker_process_init

from georisk.celery_app.base_task import PlatformTask
from georisk.db.session import init_worker_database
from georisk.settings import get_settings

settings = get_settings()
logger = logging.getLogger("georisk.celery")

app = Celery("georisk", broker=settings.redis_url, backend=settings.redis_url)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Redelivery on worker crash — safe only once command-handler
    # idempotency exists (Application Layer §11); see base_task.py's note.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_queue="light",
    # Sprint 0 Review finding #20 / Remediation #20: GDAL/rasterio/NumPy
    # native-extension memory growth across a long-running worker's
    # lifetime is a known characteristic (Infrastructure Architecture §11).
    # Recycling workers periodically is cheap insurance set now, before any
    # `gis`-queue task exists to make the need for it obvious.
    worker_max_tasks_per_child=200,
    worker_prefetch_multiplier=1,
    # Single source of truth for queue assignment. Exact names for the
    # Sprint 0 smoke tasks below; glob patterns document the intended
    # convention for each context's real tasks as they land — harmless
    # placeholders today, since no task exists at those import paths yet.
    task_routes={
        "georisk.celery_app.app.ping_gis": {"queue": "gis"},
        "georisk.celery_app.app.ping_ai": {"queue": "ai"},
        "georisk.celery_app.app.ping_light": {"queue": "light"},
        "georisk.celery_app.app.ping_system": {"queue": "system"},
        "georisk.contexts.analysis.*": {"queue": "gis"},
        "georisk.contexts.geospatial.*": {"queue": "gis"},
        "georisk.contexts.data_acquisition.*": {"queue": "gis"},
        "georisk.contexts.prediction.*": {"queue": "ai"},
        "georisk.contexts.validation.*": {"queue": "light"},
        "georisk.contexts.reporting.*": {"queue": "light"},
        "georisk.contexts.notification.*": {"queue": "light"},
    },
)

# Empty in Sprint 0 — the `beat` service (docker/entrypoints/beat.sh) starts
# cleanly against zero scheduled jobs, proving the topology before Roadmap
# Sprint 9 adds the first real periodic job (weather/sensor polling).
app.conf.beat_schedule = {}


@worker_process_init.connect
def _init_worker_database(**_kwargs: object) -> None:
    """Establishes the per-worker-process Database instance (Sprint 0
    Review finding #4 / Remediation #4) exactly once, before this process
    picks up its first task.
    """
    init_worker_database(settings.database_url, pool_size=5)
    logger.info("Worker database initialized", extra={"pid": "worker_process_init"})


# --- Sprint 0 smoke tasks --------------------------------------------------
# Prove the four-queue topology works end to end. No business logic. Safe
# to leave in place as an operational health check once Sprint 3 adds real
# tasks, or delete then — either is fine.


@app.task(base=PlatformTask, name="georisk.celery_app.app.ping_gis")
def ping_gis() -> str:
    return "pong from gis"


@app.task(base=PlatformTask, name="georisk.celery_app.app.ping_ai")
def ping_ai() -> str:
    return "pong from ai"


@app.task(base=PlatformTask, name="georisk.celery_app.app.ping_light")
def ping_light() -> str:
    return "pong from light"


@app.task(base=PlatformTask, name="georisk.celery_app.app.ping_system")
def ping_system() -> str:
    return "pong from system"
