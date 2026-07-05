"""Liveness vs. readiness, split deliberately (Sprint 0 Review finding #11 /
Remediation #11): a conflated single ``/health`` route either reports
"ready" while a dependency is down, or gets a healthy-but-momentarily-slow
instance killed by an orchestrator — bad in both directions once this is
deployed under a rolling-update strategy (Infrastructure Architecture §25).

* ``/health/live`` — the process is running. No dependency calls, ever.
* ``/health/ready`` — the process is running *and* its dependencies
  (database, Redis) are reachable.
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
    healthy = True

    db = request.app.state.db
    try:
        async with db.session() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 — readiness must not raise
        checks["database"] = f"error: {exc}"
        healthy = False

    redis_client = request.app.state.redis
    try:
        await redis_client.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001 — readiness must not raise
        checks["redis"] = f"error: {exc}"
        healthy = False

    status_code = 200 if healthy else 503
    return JSONResponse(
        status_code=status_code,
        content={"status": "ok" if healthy else "degraded", "checks": checks},
    )
