"""Liveness vs. readiness, split deliberately (Sprint 0 Review finding #11 /
Remediation #11): a conflated single ``/health`` route either reports
"ready" while a dependency is down, or gets a healthy-but-momentarily-slow
instance killed by an orchestrator — bad in both directions once this is
deployed under a rolling-update strategy (Infrastructure Architecture §25).

* ``/health/live`` — the process is running. No dependency calls, ever.
* ``/health/ready`` — the process is running *and* its dependencies
  (database, Redis) are reachable.

Sprint D task #4 (Redis graceful degradation) refined ``/ready`` further:
database and Redis are NOT equally critical. The database is load-bearing
for nearly every request this API serves; Redis today only backs rate
limiting and this health check itself (``PRODUCTION_READINESS_REPORT.md``'s
"App only declares Redis settings" — no other code path has ever had a
hard Redis dependency, and Sprint D's new rate limiter is deliberately
built to fall back to an in-process counter rather than fail when Redis is
down; see ``rate_limiting.py``). Treating a Redis outage as equally fatal
as a database outage would pull a fully-functional instance out of an
orchestrator's rotation for no real reason — exactly the "application
continues operating wherever safe" failure mode task #4 asks to close.
So: database down -> 503 "unhealthy" (this instance genuinely cannot serve
most traffic). Redis down alone -> 200 "degraded" (still receiving
traffic; rate limiting silently runs on its in-process fallback instead).
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    checks: dict[str, str] = {}

    db = request.app.state.db
    try:
        async with db.session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
        database_healthy = True
    except Exception as exc:  # noqa: BLE001 — readiness must not raise
        checks["database"] = f"error: {exc}"
        database_healthy = False

    redis_client = request.app.state.redis
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
        redis_healthy = True
    except Exception as exc:  # noqa: BLE001 — readiness must not raise
        checks["redis"] = f"error: {exc}"
        redis_healthy = False

    if not database_healthy:
        status_label, status_code = "unhealthy", 503
    elif not redis_healthy:
        status_label, status_code = "degraded", 200
    else:
        status_label, status_code = "ok", 200

    return JSONResponse(
        status_code=status_code,
        content={"status": status_label, "checks": checks},
    )
