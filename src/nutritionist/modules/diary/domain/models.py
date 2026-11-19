"""Diary model.

An entry stores a *snapshot* of the food and its per-serving nutrients at the
moment it was logged. History must not change when the food database changes,
and reading a day never needs an external API call.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Literal, Self

from nutritionist.core.ids import UserId
from nutritionist.modules.diary.domain.errors import InvalidDiaryEntryError

MIN_SERVINGS = Decimal("0.01")
MAX_SERVINGS = Decimal(100)
MAX_DAYS_IN_PAST = 366
# Users ahead of UTC (e.g. UTC+14) are already on "tomorrow" by our clock.
MAX_DAYS_IN_FUTURE = 1
_CENTI = Decimal("0.01")

EntryId = uuid.UUID


class MealType(StrEnum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"


@dataclass(frozen=True, slots=True)
class NutrientAmounts:
    """Energy and nutrients. Optional values are ``None`` when the source does not
    know them. When summing, unknown counts as nothing, never as zero-for-sure."""

    calories_kcal: Decimal
    protein_g: Decimal
    carbohydrate_g: Decimal
    fat_g: Decimal
    fiber_g: Decimal | None = None
    sugar_g: Decimal | None = None
    saturated_fat_g: Decimal | None = None
    sodium_mg: Decimal | None = None

    @classmethod
    def zero(cls) -> Self:
        return cls(Decimal(0), Decimal(0), Decimal(0), Decimal(0))

    @classmethod
    def total(cls, amounts: Iterable["NutrientAmounts"]) -> Self:
        result = cls.zero()
        for amount in amounts:
            result = result + amount
        return result

    def scaled(self, factor: Decimal) -> Self:
        def scale(value: Decimal | None) -> Decimal | None:
            return None if value is None else value * factor

        return type(self)(
            calories_kcal=self.calories_kcal * factor,
            protein_g=self.protein_g * factor,
            carbohydrate_g=self.carbohydrate_g * factor,
            fat_g=self.fat_g * factor,
            fiber_g=scale(self.fiber_g),
            sugar_g=scale(self.sugar_g),
            saturated_fat_g=scale(self.saturated_fat_g),
            sodium_mg=scale(self.sodium_mg),
        )

    def __add__(self, other: "NutrientAmounts") -> Self:
        def add(a: Decimal | None, b: Decimal | None) -> Decimal | None:
            if a is None and b is None:
                return None
            return (a or Decimal(0)) + (b or Decimal(0))

        return type(self)(
            calories_kcal=self.calories_kcal + other.calories_kcal,
            protein_g=self.protein_g + other.protein_g,
            carbohydrate_g=self.carbohydrate_g + other.carbohydrate_g,
            fat_g=self.fat_g + other.fat_g,
            fiber_g=add(self.fiber_g, other.fiber_g),
            sugar_g=add(self.sugar_g, other.sugar_g),
            saturated_fat_g=add(self.saturated_fat_g, other.saturated_fat_g),
            sodium_mg=add(self.sodium_mg, other.sodium_mg),
        )


@dataclass(frozen=True, slots=True)
class LoggedFood:
    """What was eaten, as it was known when it was logged."""

    provider: str
    food_id: str
    food_name: str
    serving_id: str
    serving_description: str
    per_serving: NutrientAmounts
    brand: str | None = None


@dataclass(frozen=True, slots=True)
class DiaryEntry:
    id: EntryId
    user_id: UserId
    day: date
    meal: MealType
    food: LoggedFood
    servings: Decimal
    logged_at: datetime

    @classmethod
    def log(
        cls,
        *,
        user_id: UserId,
        day: date,
        meal: MealType,
        food: LoggedFood,
        servings: Decimal,
        today: date,
        now: datetime,
    ) -> Self:
        _check_day(day, today)
        return cls(
            id=uuid.uuid4(),
            user_id=user_id,
            day=day,
            meal=meal,
            food=food,
            servings=_check_servings(servings),
            logged_at=now,
        )

    @property
    def nutrients(self) -> NutrientAmounts:
        return self.food.per_serving.scaled(self.servings)

    def change(self, *, servings: Decimal | None = None, meal: MealType | None = None) -> Self:
        return replace(
            self,
            servings=self.servings if servings is None else _check_servings(servings),
            meal=meal or self.meal,
        )


@dataclass(frozen=True, slots=True)
class DayTargets:
    calories_kcal: int
    protein_g: int
    carbohydrate_g: int
    fat_g: int
    fiber_g: int
    macro_split: str


TargetsSource = Literal["snapshot", "current"]


@dataclass(frozen=True, slots=True)
class Remaining:
    """Target minus eaten. Negative means over target."""

    calories_kcal: Decimal
    protein_g: Decimal
    carbohydrate_g: Decimal
    fat_g: Decimal
    fiber_g: Decimal

    @classmethod
    def of(cls, targets: DayTargets, eaten: NutrientAmounts) -> Self:
        return cls(
            calories_kcal=targets.calories_kcal - eaten.calories_kcal,
            protein_g=targets.protein_g - eaten.protein_g,
            carbohydrate_g=targets.carbohydrate_g - eaten.carbohydrate_g,
            fat_g=targets.fat_g - eaten.fat_g,
            fiber_g=targets.fiber_g - (eaten.fiber_g or Decimal(0)),
        )


@dataclass(frozen=True, slots=True)
class DailySummary:
    day: date
    entries: tuple[DiaryEntry, ...]
    totals: NutrientAmounts
    by_meal: dict[MealType, NutrientAmounts] = field(hash=False)
    targets: DayTargets | None
    targets_source: TargetsSource | None
    remaining: Remaining | None

    @classmethod
    def build(
        cls,
        day: date,
        entries: Iterable[DiaryEntry],
        targets: DayTargets | None,
        source: TargetsSource | None,
    ) -> Self:
        ordered = tuple(sorted(entries, key=lambda e: (list(MealType).index(e.meal), e.logged_at)))
        totals = NutrientAmounts.total(e.nutrients for e in ordered)
        by_meal = {
            meal: NutrientAmounts.total(e.nutrients for e in ordered if e.meal is meal)
            for meal in MealType
        }
        return cls(
            day=day,
            entries=ordered,
            totals=totals,
            by_meal=by_meal,
            targets=targets,
            targets_source=source if targets else None,
            remaining=Remaining.of(targets, totals) if targets else None,
        )


def _check_servings(servings: Decimal) -> Decimal:
    value = servings.quantize(_CENTI, ROUND_HALF_UP)
    if not MIN_SERVINGS <= value <= MAX_SERVINGS:
        raise InvalidDiaryEntryError(f"Servings must be between {MIN_SERVINGS} and {MAX_SERVINGS}.")
    return value


def _check_day(day: date, today: date) -> None:
    if day > today + timedelta(days=MAX_DAYS_IN_FUTURE):
        raise InvalidDiaryEntryError("You cannot log food for a future day.")
    if day < today - timedelta(days=MAX_DAYS_IN_PAST):
        raise InvalidDiaryEntryError(f"Entries older than {MAX_DAYS_IN_PAST} days cannot be added.")
