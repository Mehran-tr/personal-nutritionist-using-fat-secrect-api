from dataclasses import dataclass
from datetime import date
from typing import Protocol

from nutritionist.core.clock import Clock
from nutritionist.core.ids import UserId
from nutritionist.modules.coach.domain.models import CoachDay, DayReview, Insight
from nutritionist.modules.coach.domain.rules import CoachEngine


class DaySource(Protocol):
    """A diary day in coach vocabulary. Implemented in ``nutritionist.interop``."""

    async def for_day(self, user_id: UserId, day: date, today: date) -> CoachDay: ...


@dataclass(frozen=True, slots=True)
class PhraseResult:
    text: str | None = None
    pending: bool = False  # generation was started in the background


class Phraser(Protocol):
    """Turns rule-based insights into a short friendly paragraph.

    Contract: may only *rephrase*. ``text`` is ``None`` whenever it can't do that
    safely (disabled, upstream error, output failed validation) or isn't ready
    yet (``pending``). The review is always complete without it.
    """

    async def phrase(self, day: CoachDay, insights: tuple[Insight, ...]) -> PhraseResult: ...


class NoPhraser:
    async def phrase(self, day: CoachDay, insights: tuple[Insight, ...]) -> PhraseResult:
        return PhraseResult()


@dataclass(frozen=True, slots=True)
class GetDayReview:
    days: DaySource
    engine: CoachEngine
    phraser: Phraser
    clock: Clock

    async def execute(self, user_id: UserId, day: date) -> DayReview:
        coach_day = await self.days.for_day(user_id, day, self.clock.today())
        insights = self.engine.review(coach_day)
        phrased = await self.phraser.phrase(coach_day, insights) if insights else PhraseResult()
        return DayReview(day, coach_day.status, insights, phrased.text, phrased.pending)
