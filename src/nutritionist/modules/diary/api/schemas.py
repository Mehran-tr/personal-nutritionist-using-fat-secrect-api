from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, Field, PlainSerializer, model_validator

from nutritionist.modules.diary.application.use_cases import LogFoodCommand, MealItem
from nutritionist.modules.diary.domain.models import (
    MAX_SERVINGS,
    DailySummary,
    DayTargets,
    DiaryEntry,
    MealType,
    NutrientAmounts,
    Remaining,
    TargetsSource,
)


def _one_decimal(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.1"), ROUND_HALF_UP))


# Full precision internally; one decimal on the wire.
Amount = Annotated[Decimal, PlainSerializer(_one_decimal, return_type=float, when_used="json")]
Servings = Annotated[Decimal, Field(gt=0, le=MAX_SERVINGS, examples=[1.5])]


# ------------------------------------------------------------------ input


class LogFoodIn(BaseModel):
    day: date
    meal: MealType
    food_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    serving_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    servings: Servings = Decimal(1)

    def to_command(self) -> LogFoodCommand:
        return LogFoodCommand(self.day, self.meal, self.food_id, self.serving_id, self.servings)


FoodId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]


class MealItemIn(BaseModel):
    food_id: FoodId
    serving_id: FoodId
    servings: Servings = Decimal(1)

    def to_item(self) -> MealItem:
        return MealItem(self.food_id, self.serving_id, self.servings)


class LogMealIn(BaseModel):
    """Several foods eaten together: one request, one transaction, all-or-nothing."""

    day: date
    meal: MealType
    # Upper bound also enforced by settings.performance.max_batch_items.
    items: list[MealItemIn] = Field(min_length=1, max_length=100)


class UpdateEntryIn(BaseModel):
    servings: Servings | None = None
    meal: MealType | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> Self:
        if self.servings is None and self.meal is None:
            raise ValueError("Provide 'servings' and/or 'meal'.")
        return self


# ------------------------------------------------------------------ output


class NutrientsOut(BaseModel):
    calories_kcal: Amount
    protein_g: Amount
    carbohydrate_g: Amount
    fat_g: Amount
    fiber_g: Amount | None
    sugar_g: Amount | None
    saturated_fat_g: Amount | None
    sodium_mg: Amount | None

    @classmethod
    def from_domain(cls, n: NutrientAmounts) -> Self:
        return cls(
            calories_kcal=n.calories_kcal,
            protein_g=n.protein_g,
            carbohydrate_g=n.carbohydrate_g,
            fat_g=n.fat_g,
            fiber_g=n.fiber_g,
            sugar_g=n.sugar_g,
            saturated_fat_g=n.saturated_fat_g,
            sodium_mg=n.sodium_mg,
        )


class LoggedFoodOut(BaseModel):
    provider: str
    id: str
    name: str
    brand: str | None
    serving_id: str
    serving_description: str


class EntryOut(BaseModel):
    id: UUID
    day: date
    meal: MealType
    servings: Amount
    food: LoggedFoodOut
    nutrients: NutrientsOut
    logged_at: datetime

    @classmethod
    def from_domain(cls, e: DiaryEntry) -> Self:
        return cls(
            id=e.id,
            day=e.day,
            meal=e.meal,
            servings=e.servings,
            food=LoggedFoodOut(
                provider=e.food.provider,
                id=e.food.food_id,
                name=e.food.food_name,
                brand=e.food.brand,
                serving_id=e.food.serving_id,
                serving_description=e.food.serving_description,
            ),
            nutrients=NutrientsOut.from_domain(e.nutrients),
            logged_at=e.logged_at,
        )


class DayTargetsOut(BaseModel):
    calories_kcal: int
    protein_g: int
    carbohydrate_g: int
    fat_g: int
    fiber_g: int
    macro_split: str

    @classmethod
    def from_domain(cls, t: DayTargets) -> Self:
        return cls(
            calories_kcal=t.calories_kcal,
            protein_g=t.protein_g,
            carbohydrate_g=t.carbohydrate_g,
            fat_g=t.fat_g,
            fiber_g=t.fiber_g,
            macro_split=t.macro_split,
        )


class RemainingOut(BaseModel):
    calories_kcal: Amount
    protein_g: Amount
    carbohydrate_g: Amount
    fat_g: Amount
    fiber_g: Amount

    @classmethod
    def from_domain(cls, r: Remaining) -> Self:
        return cls(
            calories_kcal=r.calories_kcal,
            protein_g=r.protein_g,
            carbohydrate_g=r.carbohydrate_g,
            fat_g=r.fat_g,
            fiber_g=r.fiber_g,
        )


class DaySummaryOut(BaseModel):
    day: date
    totals: NutrientsOut
    by_meal: dict[MealType, NutrientsOut]
    targets: DayTargetsOut | None
    targets_source: TargetsSource | None = Field(
        description="'snapshot': frozen when the day's first food was logged. "
        "'current': computed from today's profile (nothing logged yet)."
    )
    remaining: RemainingOut | None
    entries: list[EntryOut]

    @classmethod
    def from_domain(cls, s: DailySummary) -> Self:
        return cls(
            day=s.day,
            totals=NutrientsOut.from_domain(s.totals),
            by_meal={meal: NutrientsOut.from_domain(n) for meal, n in s.by_meal.items()},
            targets=DayTargetsOut.from_domain(s.targets) if s.targets else None,
            targets_source=s.targets_source,
            remaining=RemainingOut.from_domain(s.remaining) if s.remaining else None,
            entries=[EntryOut.from_domain(e) for e in s.entries],
        )
