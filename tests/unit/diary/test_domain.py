from datetime import date, timedelta
from decimal import Decimal

import pytest

from nutritionist.core.ids import new_user_id
from nutritionist.modules.diary.domain.errors import InvalidDiaryEntryError
from nutritionist.modules.diary.domain.models import (
    DailySummary,
    DiaryEntry,
    MealType,
    NutrientAmounts,
)
from tests.fakes import NOW
from tests.unit.diary.fakes import OATS, TARGETS

TODAY = NOW.date()


def entry(
    meal: MealType = MealType.BREAKFAST, servings: str = "1", day: date = TODAY
) -> DiaryEntry:
    return DiaryEntry.log(
        user_id=new_user_id(),
        day=day,
        meal=meal,
        food=OATS,
        servings=Decimal(servings),
        today=TODAY,
        now=NOW,
    )


class TestNutrientAmounts:
    def test_scaling_keeps_unknowns_unknown(self) -> None:
        scaled = OATS.per_serving.scaled(Decimal("1.5"))
        assert scaled.calories_kcal == Decimal("225.0")
        assert scaled.fiber_g == Decimal("6.0")
        assert scaled.sodium_mg is None

    def test_adding_unknown_to_known_keeps_the_known_part(self) -> None:
        known = NutrientAmounts(
            Decimal(1), Decimal(1), Decimal(1), Decimal(1), sodium_mg=Decimal(5)
        )
        unknown = NutrientAmounts(Decimal(1), Decimal(1), Decimal(1), Decimal(1))
        total = known + unknown
        assert total.sodium_mg == Decimal(5)
        assert total.sugar_g is None
        assert total.calories_kcal == Decimal(2)

    def test_total_of_nothing_is_zero(self) -> None:
        assert NutrientAmounts.total([]) == NutrientAmounts.zero()


class TestDiaryEntry:
    def test_nutrients_are_per_serving_times_servings(self) -> None:
        assert entry(servings="2").nutrients.protein_g == Decimal("10")

    @pytest.mark.parametrize("servings", ["0", "-1", "100.01"])
    def test_servings_bounds(self, servings: str) -> None:
        with pytest.raises(InvalidDiaryEntryError):
            entry(servings=servings)

    def test_servings_are_rounded_to_hundredths(self) -> None:
        assert entry(servings="1.234").servings == Decimal("1.23")

    @pytest.mark.parametrize(("offset", "ok"), [(1, True), (2, False), (-366, True), (-367, False)])
    def test_day_window(self, offset: int, ok: bool) -> None:
        day = TODAY + timedelta(days=offset)
        if ok:
            assert entry(day=day).day == day
        else:
            with pytest.raises(InvalidDiaryEntryError):
                entry(day=day)

    def test_change_validates_and_keeps_identity(self) -> None:
        original = entry()
        changed = original.change(servings=Decimal(3), meal=MealType.SNACK)
        assert (changed.id, changed.servings, changed.meal) == (original.id, 3, MealType.SNACK)
        with pytest.raises(InvalidDiaryEntryError):
            original.change(servings=Decimal(0))


class TestDailySummary:
    def test_totals_by_meal_and_remaining(self) -> None:
        entries = [entry(MealType.DINNER), entry(MealType.BREAKFAST, "2")]
        summary = DailySummary.build(TODAY, entries, TARGETS, "snapshot")

        assert [e.meal for e in summary.entries] == [MealType.BREAKFAST, MealType.DINNER]
        assert summary.totals.calories_kcal == Decimal(450)
        assert summary.by_meal[MealType.BREAKFAST].calories_kcal == Decimal(300)
        assert summary.by_meal[MealType.LUNCH] == NutrientAmounts.zero()
        assert summary.remaining is not None
        assert summary.remaining.calories_kcal == Decimal(1550)
        assert summary.remaining.fiber_g == Decimal(16)

    def test_over_target_is_negative(self) -> None:
        summary = DailySummary.build(TODAY, [entry(servings="20")], TARGETS, "current")
        assert summary.remaining is not None
        assert summary.remaining.calories_kcal == Decimal(-1000)

    def test_no_targets(self) -> None:
        summary = DailySummary.build(TODAY, [], None, "current")
        assert (summary.targets, summary.targets_source, summary.remaining) == (None, None, None)
