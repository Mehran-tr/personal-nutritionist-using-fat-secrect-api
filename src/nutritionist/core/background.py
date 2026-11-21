"""In-process background tasks for work the user shouldn't wait for.

Scope: best-effort, idempotent, short work whose result is *cached*. If a task
is lost (deploy, crash), the next request simply schedules it again. LLM
phrasing is the current user. Work that must not be lost (emails, exports,
payments) needs a durable queue (arq/Celery + Redis) instead. See PERFORMANCE.md.
"""

import asyncio
from collections.abc import Awaitable, Callable

import structlog

from nutritionist.core.metrics import BACKGROUND_TASKS

logger = structlog.get_logger(__name__)


class BackgroundRunner:
    def __init__(self, concurrency: int = 4) -> None:
        self._limit = asyncio.Semaphore(concurrency)
        self._in_flight: dict[str, asyncio.Task[None]] = {}

    def spawn(self, key: str, name: str, work: Callable[[], Awaitable[object]]) -> bool:
        """Start ``work`` unless a task with the same key is already running.
        Returns True if a new task was started."""
        if key in self._in_flight:
            return False
        task = asyncio.create_task(self._run(name, work), name=f"bg:{name}")
        self._in_flight[key] = task
        task.add_done_callback(lambda _: self._in_flight.pop(key, None))
        return True

    async def _run(self, name: str, work: Callable[[], Awaitable[object]]) -> None:
        async with self._limit:
            try:
                await work()
            except Exception:
                BACKGROUND_TASKS.labels(name, "error").inc()
                logger.exception("background_task_failed", task=name)
            else:
                BACKGROUND_TASKS.labels(name, "ok").inc()

    async def aclose(self, timeout_seconds: float = 5.0) -> None:
        """On shutdown: give running tasks a moment, then cancel the rest."""
        tasks = list(self._in_flight.values())
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=timeout_seconds)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def drain(self) -> None:
        """Wait for everything currently running (tests, graceful shutdown)."""
        while self._in_flight:
            await asyncio.gather(*list(self._in_flight.values()), return_exceptions=True)
