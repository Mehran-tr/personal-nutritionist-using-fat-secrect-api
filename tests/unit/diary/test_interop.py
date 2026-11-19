from datetime import date
from decimal import Decimal

from nutritionist.core.clock import FixedClock
from nutritionist.core.ids import UserId, new_user_id
from nutritionist.interop.catalog_to_diary import CatalogFoodLookup
from nutritionist.interop.targets_to_diary import TargetsForDiary
from nutritionist.modules.catalog.application.use_cases import GetFood
from nutritionist.modules.targets.application.use_cases import GetTargets
from nutritionist.modules.targets.domain.calculator import TargetCalculator
from nutritionist.modules.targets.domain.models import (
    ActivityLevel,
    BodyStats,
    Goal,
    MacroSplit,
    Sex,
)
from tests.fakes import NOW, FakeFoodProvider, make_food


async def test_catalog_lookup_snapshots_the_chosen_serving() -> None:
    lookup = CatalogFoodLookup(GetFood(FakeFoodProvider(foods={"1": make_food("1", "Apple")})))

    food = await lookup.find("1", "1-100g")

    assert food is not None
    assert (food.food_name, food.serving_description) == ("Apple", "100 g")
    assert food.per_serving.calories_kcal == Decimal(52)
    assert food.per_serving.fiber_g == Decimal("2.4")
    assert await lookup.find("1", "unknown-serving") is None
    assert await lookup.find("404", "1-100g") is None


class _Stats:
    def __init__(self, stats: BodyStats | None) -> None:
        self.stats = stats

    async def for_user(self, user_id: UserId, on: date) -> BodyStats | None:
        return self.stats


async def test_targets_for_diary_uses_preferred_split_and_handles_no_profile() -> None:
    stats = BodyStats(
        Sex.MALE,
        30,
        Decimal(180),
        Decimal(80),
        ActivityLevel.MODERATE,
        Goal.MAINTAIN,
        preferred_split=MacroSplit.LOW_CARB,
    )
    lookup = TargetsForDiary(GetTargets(_Stats(stats), TargetCalculator(), FixedClock(NOW)))

    targets = await lookup.for_day(new_user_id(), NOW.date())

    assert targets is not None
    assert targets.macro_split == "low_carb"
    assert targets.calories_kcal == 2760

    none = TargetsForDiary(GetTargets(_Stats(None), TargetCalculator(), FixedClock(NOW)))
    assert await none.for_day(new_user_id(), NOW.date()) is None
