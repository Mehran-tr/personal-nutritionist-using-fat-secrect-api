import asyncio
import io
from datetime import date
from decimal import Decimal

import pytest

from nutritionist.core.background import BackgroundRunner
from nutritionist.core.cache import InMemoryCache
from nutritionist.core.logging import QueueWriter
from nutritionist.modules.catalog.infrastructure.cached_provider import CachedFoodProvider
from nutritionist.modules.coach.domain.models import (
    CoachDay,
    DayStatus,
    Insight,
    InsightCode,
    Intake,
    Severity,
)
from nutritionist.modules.coach.infrastructure.phrasers import CachedPhraser
from tests.fakes import FakeFoodProvider, make_food


class SlowProvider(FakeFoodProvider):
    async def get(self, external_id: str):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.05)
        return await super().get(external_id)


async def test_concurrent_cache_misses_share_one_upstream_call() -> None:
    inner = SlowProvider(foods={"1": make_food("1")})
    provider = CachedFoodProvider(
        inner, InMemoryCache(), namespace="t", food_ttl_seconds=60, search_ttl_seconds=60
    )

    results = await asyncio.gather(*(provider.get("1") for _ in range(25)))

    assert inner.calls == ["get:1"]
    assert all(r == results[0] for r in results)


async def test_failed_load_is_not_stuck_in_flight() -> None:
    inner = FakeFoodProvider(error=RuntimeError("upstream down"))
    provider = CachedFoodProvider(
        inner, InMemoryCache(), namespace="t", food_ttl_seconds=60, search_ttl_seconds=60
    )
    for _ in range(2):  # the second call must try again, not reuse the failed task
        with pytest.raises(RuntimeError):
            await provider.get("1")
    assert len(inner.calls) == 2


async def test_background_runner_dedupes_limits_and_survives_errors() -> None:
    runner = BackgroundRunner(concurrency=2)
    running, peak, done = 0, 0, []

    async def work(i: int) -> None:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        done.append(i)

    async def boom() -> None:
        raise RuntimeError("ignored")

    assert runner.spawn("a", "t", lambda: work(1))
    assert not runner.spawn("a", "t", lambda: work(99))  # same key: deduplicated
    for i in range(2, 6):
        runner.spawn(f"k{i}", "t", lambda i=i: work(i))
    runner.spawn("x", "t", boom)
    await runner.drain()

    assert sorted(done) == [1, 2, 3, 4, 5]
    assert peak <= 2


async def test_background_runner_cancels_stragglers_on_shutdown() -> None:
    runner = BackgroundRunner()
    runner.spawn("slow", "t", lambda: asyncio.sleep(60))
    await runner.aclose(timeout_seconds=0.05)
    assert not runner._in_flight


DAY = CoachDay(
    date(2026, 11, 18),
    DayStatus.COMPLETE,
    Intake(Decimal(1), Decimal(1), Decimal(1), Decimal(1)),
    None,
    1,
)
INSIGHTS = (Insight(InsightCode.ON_TRACK, Severity.INFO, "Calories and protein were on target."),)


class Generator:
    def __init__(self) -> None:
        self.calls = 0

    async def phrase(self, day: CoachDay, insights: tuple[Insight, ...]) -> str | None:
        self.calls += 1
        await asyncio.sleep(0.01)
        return "Nice and steady."


async def test_llm_phrasing_never_blocks_the_request() -> None:
    generator, runner = Generator(), BackgroundRunner()
    phraser = CachedPhraser(generator, InMemoryCache(), ttl_seconds=60, model="m", runner=runner)

    first = await phraser.phrase(DAY, INSIGHTS)
    second = await phraser.phrase(DAY, INSIGHTS)  # still running: no duplicate job
    await runner.drain()
    third = await phraser.phrase(DAY, INSIGHTS)

    assert (first.text, first.pending) == (None, True)
    assert second.pending
    assert (third.text, third.pending) == ("Nice and steady.", False)
    assert generator.calls == 1


def test_queue_writer_delivers_lines_in_order() -> None:
    out = io.StringIO()
    writer = QueueWriter(out)
    for i in range(100):
        writer.write(f"{i}\n")
    writer.close()
    assert out.getvalue().splitlines() == [str(i) for i in range(100)]
