"""Sprint D — unit tests for ``RateLimiter`` (rate_limiting.py): the fixed-
window counter logic itself, both the Redis-backed path (a minimal fake
pipeline, no real Redis needed) and the in-process fallback used when
Redis is unreachable. No database, no FastAPI app — pure logic.
"""

from __future__ import annotations

import pytest

from georisk.rate_limiting import RateLimiter, _InMemoryWindowCounter
from georisk.shared_kernel.errors import RateLimitExceededError

pytestmark = pytest.mark.unit


def test_in_memory_counter_allows_up_to_the_limit_then_blocks() -> None:
    counter = _InMemoryWindowCounter()
    results = [counter.hit("k", limit=3, window_seconds=60)[0] for _ in range(5)]
    assert results == [True, True, True, False, False]


def test_in_memory_counter_scopes_independently_by_key() -> None:
    counter = _InMemoryWindowCounter()
    for _ in range(3):
        counter.hit("a", limit=3, window_seconds=60)
    allowed, _ = counter.hit("b", limit=3, window_seconds=60)
    assert allowed is True


async def test_rate_limiter_with_no_redis_falls_back_to_in_memory() -> None:
    limiter = RateLimiter(redis_client=None)
    for _ in range(3):
        await limiter.enforce("bucket:1.2.3.4", limit=3, window_seconds=60)
    with pytest.raises(RateLimitExceededError):
        await limiter.enforce("bucket:1.2.3.4", limit=3, window_seconds=60)


class _BrokenRedis:
    """Simulates Redis being unreachable — every call raises, exactly like
    a real ``redis.asyncio`` client would when the connection is refused.
    """

    def pipeline(self) -> _BrokenRedis:
        return self

    def incr(self, *_args: object, **_kwargs: object) -> None:
        return None

    def expire(self, *_args: object, **_kwargs: object) -> None:
        return None

    async def execute(self) -> None:
        raise ConnectionError("Redis is unreachable in this test")


async def test_rate_limiter_degrades_to_in_memory_when_redis_is_down() -> None:
    """Task #4's "graceful fallback": Redis raising must not 500 the
    request — the limiter silently falls back to the in-process counter
    for that check instead."""
    limiter = RateLimiter(redis_client=_BrokenRedis())
    for _ in range(2):
        await limiter.enforce("bucket:5.6.7.8", limit=2, window_seconds=60)
    with pytest.raises(RateLimitExceededError) as exc_info:
        await limiter.enforce("bucket:5.6.7.8", limit=2, window_seconds=60)
    assert exc_info.value.retry_after_seconds >= 1


class _FakeRedisPipeline:
    def __init__(self, store: dict[str, int]) -> None:
        self._store = store
        self._ops: list[tuple[str, str]] = []

    def incr(self, key: str) -> _FakeRedisPipeline:
        self._ops.append(("incr", key))
        return self

    def expire(self, key: str, _seconds: int) -> _FakeRedisPipeline:
        self._ops.append(("expire", key))
        return self

    async def execute(self) -> list[int]:
        results = []
        for op, key in self._ops:
            if op == "incr":
                self._store[key] = self._store.get(key, 0) + 1
                results.append(self._store[key])
            else:
                results.append(1)
        return results


class _FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, int] = {}

    def pipeline(self) -> _FakeRedisPipeline:
        return _FakeRedisPipeline(self._store)


async def test_rate_limiter_uses_redis_when_reachable() -> None:
    limiter = RateLimiter(redis_client=_FakeRedis())
    for _ in range(4):
        await limiter.enforce("bucket:9.9.9.9", limit=4, window_seconds=60)
    with pytest.raises(RateLimitExceededError):
        await limiter.enforce("bucket:9.9.9.9", limit=4, window_seconds=60)
