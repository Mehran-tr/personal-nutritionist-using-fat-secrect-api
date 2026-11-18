"""Time as a dependency. Business rules (age, token expiry, "today's diary") are
tested with a fixed clock instead of patching datetime."""

from datetime import UTC, date, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware, in UTC."""
        ...

    def today(self) -> date: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def today(self) -> date:
        return self.now().date()


class FixedClock:
    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock needs a timezone-aware datetime.")
        self.at = at

    def now(self) -> datetime:
        return self.at

    def today(self) -> date:
        return self.at.date()
