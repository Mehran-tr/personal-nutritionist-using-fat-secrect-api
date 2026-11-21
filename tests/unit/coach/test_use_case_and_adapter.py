from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from nutritionist.core.clock import FixedClock
from nutritionist.core.ids import UserId, new_user_id
from nutritionist.interop.diary_to_coach import DiaryDaySource
from nutritionist.modules.coach.application.use_cases import (
    GetDayReview,
    NoPhraser,
    PhraseResult,
)
from nutritionist.modules.coach.domain.models import CoachDay, DayStatus, Insight, InsightCode
from nutritionist.modules.coach.domain.rules import CoachEngine
from nutritionist.modules.diary.application.use_cases import (
    GetDailySummary,
    LogFood,
    LogFoodCommand,
)
from nutritionist.modules.diary.domain.models import MealType
from tests.fakes import NOW
from tests.unit.diary.fakes import OATS, FakeDiaryUow, FakeFoods, FakeTargets

TODAY = NOW.date()
YESTERDAY = TODAY - timedelta(days=1)


async def test_adapter_maps_summary_status_and_missing_data() -> None:
    uow, user = FakeDiaryUow(), new_user_id()
    salty = replace(
        OATS, food_id="11", per_serving=replace(OATS.per_serving, sodium_mg=Decimal(400))
    )
    log = LogFood(uow, FakeFoods(OATS, salty), FakeTargets(), FixedClock(NOW))
    for food_id in ("10", "11"):
        await log.execute(
            user, LogFoodCommand(YESTERDAY, MealType.LUNCH, food_id, "s40", Decimal(2))
        )
    source = DiaryDaySource(GetDailySummary(uow, FakeTargets()))

    past = await source.for_day(user, YESTERDAY, TODAY)
    current = await source.for_day(user, TODAY, TODAY)

    assert past.status is DayStatus.COMPLETE
    assert current.status is DayStatus.IN_PROGRESS
    assert past.entry_count == 2
    assert past.intake.calories_kcal == Decimal(600)
    assert past.intake.sodium_mg == Decimal(800)  # known part only
    assert past.goals is not None
    assert past.goals.calories_kcal == 2000
    assert past.entries_missing == {"fiber": 0, "sugar": 2, "saturated fat": 2, "sodium": 1}


class Source:
    def __init__(self, coach_day: CoachDay) -> None:
        self.coach_day = coach_day

    async def for_day(self, user_id: UserId, day: date, today: date) -> CoachDay:
        return self.coach_day


class Spy:
    def __init__(self) -> None:
        self.seen: tuple[Insight, ...] | None = None

    async def phrase(self, day: CoachDay, insights: tuple[Insight, ...]) -> PhraseResult:
        self.seen = insights
        return PhraseResult("Friendly summary.")


async def test_review_combines_engine_and_phraser() -> None:
    uow, user = FakeDiaryUow(), new_user_id()
    coach_day = await DiaryDaySource(GetDailySummary(uow, FakeTargets())).for_day(
        user, YESTERDAY, TODAY
    )
    spy = Spy()

    review = await GetDayReview(Source(coach_day), CoachEngine(), spy, FixedClock(NOW)).execute(
        user, YESTERDAY
    )

    assert [i.code for i in review.insights] == [InsightCode.NOTHING_LOGGED]
    assert spy.seen == review.insights
    assert review.summary == "Friendly summary."

    plain = await GetDayReview(
        Source(coach_day), CoachEngine(), NoPhraser(), FixedClock(NOW)
    ).execute(user, YESTERDAY)
    assert plain.summary is None
