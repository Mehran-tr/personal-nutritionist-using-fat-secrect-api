"""Rate-limit port: fixed-window counters for throttling and login lockout.

Implementations live in ``core.rate_limit_stores`` (Redis, in-memory, fail-open).

Fixed windows allow at most 2x the limit around a window boundary. That is fine
for abuse protection, which is the only use here. Redis is used in production so
limits are shared by all API replicas; the in-memory version is for tests/dev.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class WindowState:
    count: int
    retry_after_seconds: int  # until the current window resets (0 = no window open)


class RateLimiter(Protocol):
    async def hit(self, key: str, window_seconds: int) -> WindowState:
        """Count one event in the key's current window and return the new state."""
        ...

    async def peek(self, key: str) -> WindowState:
        """Current state without counting anything."""
        ...

    async def reset(self, key: str) -> None: ...
