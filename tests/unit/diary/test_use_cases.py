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
    UpdateEntry,
)
from nutritionist.modules.diary.domain.errors import (
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
