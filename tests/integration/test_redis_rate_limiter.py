"""The production limiter against a real Redis (skipped if none is running)."""

import os
from collections.abc import AsyncIterator

import pytest
from redis.asyncio import Redis

from nutritionist.core.rate_limit_stores import RedisRateLimiter

REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6390/15")


@pytest.fixture
async def limiter() -> AsyncIterator[RedisRateLimiter]:
    client = Redis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception:
        await client.aclose()
        if os.environ.get("CI") == "true":
            raise
        pytest.skip(f"Redis not reachable at {REDIS_URL}")
    await client.flushdb()
    yield RedisRateLimiter(client, prefix="test")
    await client.flushdb()
    await client.aclose()


async def test_window_counts_and_starts_once(limiter: RedisRateLimiter) -> None:
    first = await limiter.hit("k", 60)
    second = await limiter.hit("k", 60)
    assert (first.count, second.count) == (1, 2)
    assert 0 < second.retry_after_seconds <= 60

    peeked = await limiter.peek("k")
    assert peeked.count == 2
    await limiter.reset("k")
    assert (await limiter.peek("k")).count == 0


async def test_window_is_not_extended_by_later_hits(limiter: RedisRateLimiter) -> None:
    await limiter.hit("k", 2)
    state = await limiter.hit("k", 600)  # NX: the original 2 s window stays
    assert state.retry_after_seconds <= 2
