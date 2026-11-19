"""Targets vocabulary.

This module deliberately has its *own* Sex/ActivityLevel/Goal types instead of
importing the profile module's. The two are mapped in ``nutritionist.interop``,
so profile can evolve (new goals, new fields) without breaking target maths.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class Sex(StrEnum):
    FEMALE = "female"
    MALE = "male"


class ActivityLevel(StrEnum):
    SEDENTARY = "sedentary"
    LIGHT = "light"
    MODERATE = "moderate"
    ACTIVE = "active"
    VERY_ACTIVE = "very_active"


class Goal(StrEnum):
    LOSE_WEIGHT = "lose_weight"
    MAINTAIN = "maintain"
    GAIN_WEIGHT = "gain_weight"


class MacroSplit(StrEnum):
    BALANCED = "balanced"
    HIGH_PROTEIN = "high_protein"
    LOW_CARB = "low_carb"


class Adjustment(StrEnum):
    """Why the result differs from the textbook formula. Shown to the user."""

    CALORIE_FLOOR_APPLIED = "calorie_floor_applied"
    DEFICIT_CAPPED = "deficit_capped"
    SURPLUS_CAPPED = "surplus_capped"
    PROTEIN_BASED_ON_REFERENCE_WEIGHT = "protein_based_on_reference_weight"
    PROTEIN_CAPPED = "protein_capped"


@dataclass(frozen=True, slots=True)
class BodyStats:
    sex: Sex
    age_years: int
    height_cm: Decimal
    weight_kg: Decimal
    activity_level: ActivityLevel
    goal: Goal

    @property
    def bmi(self) -> Decimal:
        height_m = self.height_cm / 100
        return self.weight_kg / (height_m * height_m)


@dataclass(frozen=True, slots=True)
class MacroTargets:
    protein_g: int
    carbohydrate_g: int
    fat_g: int
    fiber_g: int


@dataclass(frozen=True, slots=True)
class NutritionTargets:
    formula: str
    macro_split: MacroSplit
    bmr_kcal: int
    tdee_kcal: int
    calories_kcal: int
    macros: MacroTargets
    adjustments: tuple[Adjustment, ...]
