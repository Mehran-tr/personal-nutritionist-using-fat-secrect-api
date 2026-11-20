import pytest

from nutritionist.core.rate_limit_stores import FailOpenRateLimiter, InMemoryRateLimiter


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def test_fixed_window_counts_and_resets() -> None:
    clock = Clock()
    limiter = InMemoryRateLimiter(clock)

    assert (await limiter.hit("k", 60)).count == 1
    state = await limiter.hit("k", 60)
    assert (state.count, state.retry_after_seconds) == (2, 60)

    clock.now += 30
    assert (await limiter.peek("k")).retry_after_seconds == 30
    clock.now += 31
    assert (await limiter.peek("k")).count == 0
    assert (await limiter.hit("k", 60)).count == 1

    await limiter.reset("k")
    assert (await limiter.peek("k")).count == 0


class Broken:
    async def hit(self, key: str, window_seconds: int) -> None:
        raise ConnectionError

    async def peek(self, key: str) -> None:
        raise ConnectionError

    async def reset(self, key: str) -> None:
        raise ConnectionError


@pytest.mark.parametrize("operation", ["hit", "peek", "reset"])
async def test_store_outage_fails_open(operation: str) -> None:
    limiter = FailOpenRateLimiter(Broken())  # type: ignore[arg-type]
    method = getattr(limiter, operation)
    result = await (method("k", 60) if operation == "hit" else method("k"))
    assert result is None or result.count == 0
