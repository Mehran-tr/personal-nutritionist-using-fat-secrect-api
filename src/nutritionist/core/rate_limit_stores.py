"""Rate-limiter stores. Kept apart from the port so application code never
imports Redis."""

import time
from collections.abc import Callable

import structlog
from redis.asyncio import Redis

from nutritionist.core.rate_limit import RateLimiter, WindowState

logger = structlog.get_logger(__name__)


class RedisRateLimiter:
    def __init__(self, client: Redis, prefix: str = "rl") -> None:
        self._client = client
        self._prefix = prefix

    @classmethod
    def from_url(cls, url: str) -> "RedisRateLimiter":
        return cls(Redis.from_url(url))

    async def hit(self, key: str, window_seconds: int) -> WindowState:
        full = f"{self._prefix}:{key}"
        async with self._client.pipeline(transaction=True) as pipe:
            pipe.incr(full)
            pipe.expire(full, window_seconds, nx=True)  # starts the window on first hit only
            pipe.ttl(full)
            count, _, ttl = await pipe.execute()
        return WindowState(int(count), max(int(ttl), 0))

    async def peek(self, key: str) -> WindowState:
        full = f"{self._prefix}:{key}"
        async with self._client.pipeline(transaction=False) as pipe:
            pipe.get(full)
            pipe.ttl(full)
            raw, ttl = await pipe.execute()
        return WindowState(int(raw or 0), max(int(ttl), 0))

    async def reset(self, key: str) -> None:
        await self._client.delete(f"{self._prefix}:{key}")

    async def aclose(self) -> None:
        await self._client.aclose()


class InMemoryRateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._windows: dict[str, tuple[int, float]] = {}

    async def hit(self, key: str, window_seconds: int) -> WindowState:
        now = self._clock()
        count, reset_at = self._windows.get(key, (0, 0.0))
        if reset_at <= now:
            count, reset_at = 0, now + window_seconds
        self._windows[key] = (count + 1, reset_at)
        return WindowState(count + 1, _seconds_until(reset_at, now))

    async def peek(self, key: str) -> WindowState:
        now = self._clock()
        count, reset_at = self._windows.get(key, (0, 0.0))
        if reset_at <= now:
            return WindowState(0, 0)
        return WindowState(count, _seconds_until(reset_at, now))

    async def reset(self, key: str) -> None:
        self._windows.pop(key, None)

    async def aclose(self) -> None:
        self._windows.clear()


def _seconds_until(deadline: float, now: float) -> int:
    return max(int(deadline - now + 0.999), 1)


class FailOpenRateLimiter:
    """If the limiter's store is down, allow the request and log it.

    Availability over strictness: a Redis outage must not lock every user out.
    The trade-off (brute force is only slowed by Argon2 during an outage) is
    documented in SECURITY.md, and the log line makes the outage alertable.
    """

    def __init__(self, inner: RateLimiter) -> None:
        self._inner = inner

    async def hit(self, key: str, window_seconds: int) -> WindowState:
        try:
            return await self._inner.hit(key, window_seconds)
        except Exception:
            _log_store_down("hit")
            return WindowState(0, 0)

    async def peek(self, key: str) -> WindowState:
        try:
            return await self._inner.peek(key)
        except Exception:
            _log_store_down("peek")
            return WindowState(0, 0)

    async def reset(self, key: str) -> None:
        try:
            await self._inner.reset(key)
        except Exception:
            _log_store_down("reset")


def _log_store_down(operation: str) -> None:
    logger.error("rate_limiter_unavailable", operation=operation)
