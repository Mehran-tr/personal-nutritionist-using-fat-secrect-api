from dataclasses import replace
from decimal import Decimal

import pytest

from nutritionist.core.clock import FixedClock
from nutritionist.core.ids import new_user_id
from nutritionist.modules.diary.application.use_cases import (
    DeleteEntry,
    GetDailySummary,
    LogFood,
    LogFoodCommand,
    MealItem,
    UpdateEntry,
)
from nutritionist.modules.diary.domain.errors import (
    DayFullError,
    DiaryEntryNotFoundError,
    FoodOrServingNotFoundError,
)
from nutritionist.modules.diary.domain.models import MealType
from tests.fakes import NOW
from tests.unit.diary.fakes import OATS, TARGETS, FakeDiaryUow, FakeFoods, FakeTargets

TODAY = NOW.date()
USER = new_user_id()


def command(food_id: str = "10", serving_id: str = "s40", servings: str = "1") -> LogFoodCommand:
    return LogFoodCommand(TODAY, MealType.BREAKFAST, food_id, serving_id, Decimal(servings))


def log_food(uow: FakeDiaryUow, targets: FakeTargets | None = None) -> LogFood:
    return LogFood(uow, FakeFoods(OATS), targets or FakeTargets(), FixedClock(NOW))


class TestLogFood:
    async def test_stores_snapshot_and_freezes_day_targets(self) -> None:
        uow = FakeDiaryUow()
        entry = await log_food(uow).execute(USER, command(servings="2"))

        assert uow.entries.rows[entry.id].food == OATS
        assert entry.nutrients.calories_kcal == Decimal(300)
        assert uow.day_targets.rows[(USER, TODAY)] == TARGETS
        assert uow.commits == 1

    async def test_first_log_of_the_day_wins(self) -> None:
        uow = FakeDiaryUow()
        await log_food(uow).execute(USER, command())
        changed = FakeTargets(replace(TARGETS, calories_kcal=1500))
        await log_food(uow, changed).execute(USER, command())

        assert uow.day_targets.rows[(USER, TODAY)].calories_kcal == 2000

    async def test_logging_works_without_a_profile(self) -> None:
        uow = FakeDiaryUow()
        await log_food(uow, FakeTargets(None)).execute(USER, command())
        assert len(uow.entries.rows) == 1
        assert uow.day_targets.rows == {}

    @pytest.mark.parametrize(("food_id", "serving_id"), [("999", "s40"), ("10", "nope")])
    async def test_unknown_food_or_serving(self, food_id: str, serving_id: str) -> None:
        uow = FakeDiaryUow()
        with pytest.raises(FoodOrServingNotFoundError):
            await log_food(uow).execute(USER, command(food_id, serving_id))
        assert uow.commits == 0


class TestOwnership:
    async def test_other_users_entries_are_invisible(self) -> None:
        uow = FakeDiaryUow()
        entry = await log_food(uow).execute(USER, command())
        intruder = new_user_id()

        with pytest.raises(DiaryEntryNotFoundError):
            await UpdateEntry(uow).execute(intruder, entry.id, servings=Decimal(5))
        with pytest.raises(DiaryEntryNotFoundError):
            await DeleteEntry(uow).execute(intruder, entry.id)
        assert uow.entries.rows[entry.id] == entry

    async def test_owner_can_update_and_delete(self) -> None:
        uow = FakeDiaryUow()
        entry = await log_food(uow).execute(USER, command())

        updated = await UpdateEntry(uow).execute(USER, entry.id, meal=MealType.SNACK)
        assert updated.meal is MealType.SNACK
        await DeleteEntry(uow).execute(USER, entry.id)
        assert uow.entries.rows == {}


class TestDailySummary:
    async def test_prefers_the_frozen_snapshot(self) -> None:
        uow = FakeDiaryUow()
        await log_food(uow).execute(USER, command())
        later = FakeTargets(replace(TARGETS, calories_kcal=1500))

        summary = await GetDailySummary(uow, later).execute(USER, TODAY)

        assert summary.targets_source == "snapshot"
        assert summary.targets == TARGETS

    async def test_falls_back_to_current_targets_without_writing(self) -> None:
        uow = FakeDiaryUow()
        summary = await GetDailySummary(uow, FakeTargets()).execute(USER, TODAY)

        assert summary.targets_source == "current"
        assert summary.entries == ()
        assert uow.day_targets.rows == {}
        assert uow.commits == 0


class CountingTargets(FakeTargets):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def for_day(self, user_id, day):  # type: ignore[no-untyped-def]
        self.calls += 1
        return await super().for_day(user_id, day)


class TestPerformanceBehaviour:
    async def test_targets_are_computed_once_per_day_not_per_log(self) -> None:
        uow, targets = FakeDiaryUow(), CountingTargets()
        log = LogFood(uow, FakeFoods(OATS), targets, FixedClock(NOW))
        for _ in range(5):
            await log.execute(USER, command())
        assert targets.calls == 1

    async def test_meal_batch_is_all_or_nothing(self) -> None:
        uow = FakeDiaryUow()
        log = LogFood(uow, FakeFoods(OATS), FakeTargets(), FixedClock(NOW))
        items = [MealItem("10", "s40", Decimal(1)), MealItem("missing", "s40", Decimal(1))]

        with pytest.raises(FoodOrServingNotFoundError):
            await log.execute_many(USER, TODAY, MealType.LUNCH, items)
        assert uow.entries.rows == {}

        ok = await log.execute_many(USER, TODAY, MealType.LUNCH, [items[0]] * 3)
        assert len(ok) == 3
        assert uow.commits == 1  # one transaction for the whole meal

    async def test_day_capacity(self) -> None:
        uow = FakeDiaryUow()
        log = LogFood(uow, FakeFoods(OATS), FakeTargets(), FixedClock(NOW), max_entries_per_day=2)
        await log.execute_many(USER, TODAY, MealType.LUNCH, [MealItem("10", "s40", Decimal(1))] * 2)
        with pytest.raises(DayFullError):
            await log.execute(USER, command())
