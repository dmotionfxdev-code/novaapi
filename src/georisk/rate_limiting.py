"""Application-layer rate limiting (Sprint D task #2).

Redis-backed fixed-window counters when Redis is reachable — shared across
every worker process, so the limit is real under a multi-process/multi-
instance deployment. When Redis is unreachable (a known, expected
condition on this platform's target hosting per ``PRODUCTION_READINESS_
REPORT.md``), silently falls back to an in-process counter instead of
either failing the request open (no protection at all) or failing it
closed (a Redis outage taking down login/registration/every protected
endpoint would be strictly worse than no rate limiting). The in-process
fallback is a deliberately-scoped degradation: it only approximates the
limit correctly on a single worker process, not across a fleet — accepted
because it still stops the dominant abuse case (a single client hammering
one endpoint) even in that condition, per task #4's "application continues
operating wherever safe."

Deliberately a top-level module (peer to ``db``/``observability``/
``settings.py``), not nested under ``api`` or any ``contexts.*`` package,
and with zero imports from either — the same "generic infrastructure any
layer may depend on" position ``db.session`` already occupies (every
``contexts.*.interface`` route module already imports ``get_session``
directly). Putting this under ``api.middleware`` instead would have meant
either duplicating it per context or having a context's interface layer
import from the composition root (``georisk.api``) to get at
``rate_limit_by_tenant`` — backwards from how this codebase's composition-
root pattern is supposed to flow (``api`` depends on contexts, never the
reverse). ``rate_limit_by_tenant`` below stays context-agnostic by taking
the tenant-id-resolving dependency as a parameter rather than importing
Identity's ``get_current_claims`` itself; each calling route module
supplies its own (it already imports Identity's dependencies for its own
``require_permission`` checks, so this adds no new dependency edge there).

Deliberately does NOT use ``from __future__ import annotations`` (unlike
almost every other module in this codebase) — ``rate_limit_by_tenant``'s
inner ``_dependency`` puts a closure-captured variable (the caller-supplied
``tenant_id_dependency``) inside an ``Annotated[..., Depends(...)]``
annotation. With postponed evaluation active, that annotation is stored as
a plain string and FastAPI resolves it later via ``typing.get_type_hints``
using the function's ``__globals__`` — which does NOT include closure
variables, so it can't find ``tenant_id_dependency`` and silently falls
back to treating the parameter as a plain (and therefore "missing") query
parameter, breaking every route that uses ``rate_limit_by_tenant``. Caught
by actually running the full integration suite against real Postgres
during this sprint's validation (27 tests failed with a `"loc":
["query", "tenant_id"]` 422 the first time this file had the future
import), not assumed correct from reading the code — confirmed with a
minimal reproduction before applying this fix.
"""

import time
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request

from georisk.shared_kernel.errors import RateLimitExceededError

RateLimitDependency = Callable[..., Awaitable[None]]


class _InMemoryWindowCounter:
    """Fixed-window counter, one process, one dict. Not thread-safe beyond
    what a single-threaded asyncio event loop already guarantees between
    ``await`` points — this method has none, so no lock is needed.
    """

    def __init__(self) -> None:
        self._windows: dict[str, tuple[int, int]] = {}

    def hit(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = int(time.time())
        window_start = (now // window_seconds) * window_seconds
        current_start, count = self._windows.get(key, (window_start, 0))
        if current_start != window_start:
            current_start, count = window_start, 0
        count += 1
        self._windows[key] = (current_start, count)
        retry_after = max((current_start + window_seconds) - now, 1)
        return count <= limit, retry_after


class RateLimiter:
    """Composed once per app in ``api/app.py``'s lifespan (``app.state.
    rate_limiter``), given a dedicated ``redis.asyncio`` client (Sprint 0's
    long-unused ``settings.redis_ratelimit_url``).
    """

    def __init__(self, redis_client: object | None) -> None:
        self._redis = redis_client
        self._fallback = _InMemoryWindowCounter()

    async def enforce(self, key: str, *, limit: int, window_seconds: int) -> None:
        allowed, retry_after = await self._check(key, limit=limit, window_seconds=window_seconds)
        if not allowed:
            raise RateLimitExceededError(
                f"Too many requests — try again in {retry_after} seconds",
                retry_after_seconds=retry_after,
            )

    async def _check(self, key: str, *, limit: int, window_seconds: int) -> tuple[bool, int]:
        redis_client = self._redis
        if redis_client is not None:
            try:
                return await self._check_redis(
                    redis_client, key, limit=limit, window_seconds=window_seconds
                )
            except Exception:  # noqa: BLE001 — Redis being down must degrade, not 500 the request
                pass
        return self._fallback.hit(key, limit=limit, window_seconds=window_seconds)

    async def _check_redis(
        self, redis_client: object, key: str, *, limit: int, window_seconds: int
    ) -> tuple[bool, int]:
        now = int(time.time())
        window_start = (now // window_seconds) * window_seconds
        redis_key = f"ratelimit:{key}:{window_start}"
        pipe = redis_client.pipeline()  # type: ignore[attr-defined]
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds)
        count, _ = await pipe.execute()
        retry_after = max((window_start + window_seconds) - now, 1)
        return int(count) <= limit, retry_after


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _limit_for(request: Request, bucket: str) -> tuple[int, int]:
    """Reads ``(limit, window_seconds)`` from ``app.state.rate_limits`` —
    populated in ``api/app.py``'s lifespan from the *explicit* ``Settings``
    instance ``create_app(settings=...)`` was given, deliberately NOT from
    ``get_settings()``'s process-wide ``lru_cache`` (several existing
    dependencies, e.g. ``get_access_token_issuer``, do read that cache —
    harmless for them since issuing and decoding both read the same cache
    consistently, but wrong for a per-test-tunable numeric limit: a test
    building ``create_app(settings=Settings(rate_limit_login_per_minute=3))``
    needs ITS OWN override to actually take effect, not whichever
    ``Settings()`` happened to be constructed first in the process —
    exactly the failure mode ``_make_lifespan``'s own module docstring
    already documents and rejects for ``app.state.db``).
    """
    return request.app.state.rate_limits[bucket]


def rate_limit_by_ip(bucket: str) -> RateLimitDependency:
    """For unauthenticated endpoints (login, registration, password reset,
    token refresh) — there is no tenant/user identity yet to key on."""

    async def _dependency(request: Request) -> None:
        limiter: RateLimiter = request.app.state.rate_limiter
        limit, window_seconds = _limit_for(request, bucket)
        await limiter.enforce(
            f"{bucket}:{_client_ip(request)}", limit=limit, window_seconds=window_seconds
        )

    return _dependency


def rate_limit_by_tenant(
    bucket: str, *, tenant_id_dependency: Callable[..., object]
) -> RateLimitDependency:
    """For authenticated execution endpoints (analysis/prediction/upload) —
    keyed per-tenant so one noisy tenant can't exhaust another's quota.
    ``tenant_id_dependency`` is supplied by the calling route module (e.g.
    a small local adapter over Identity's own ``get_current_claims`` it
    already depends on for ``require_permission``) rather than imported
    here, keeping this module free of any ``contexts.*`` dependency.
    """

    async def _dependency(
        request: Request,
        tenant_id: Annotated[object, Depends(tenant_id_dependency)],
    ) -> None:
        limiter: RateLimiter = request.app.state.rate_limiter
        limit, window_seconds = _limit_for(request, bucket)
        await limiter.enforce(f"{bucket}:{tenant_id}", limit=limit, window_seconds=window_seconds)

    return _dependency
