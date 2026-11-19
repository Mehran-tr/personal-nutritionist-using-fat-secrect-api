"""The user's body and goals: the inputs for every nutrition target we compute."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from nutritionist.core.ids import UserId
from nutritionist.modules.profile.domain.errors import InvalidProfileError

# Adults only: the energy equations used for targets (Mifflin-St Jeor etc.) are
# validated for adults, and advising minors on intake needs a different product.
MIN_AGE_YEARS = 18
MAX_AGE_YEARS = 100
HEIGHT_CM_RANGE = (Decimal(100), Decimal(250))
WEIGHT_KG_RANGE = (Decimal(30), Decimal(300))
_ONE_DECIMAL = Decimal("0.1")


class Sex(StrEnum):
    """Biological sex, as required by BMR equations."""

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


class DietaryPreference(StrEnum):
    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    PESCATARIAN = "pescatarian"
    HALAL = "halal"
    KOSHER = "kosher"
    GLUTEN_FREE = "gluten_free"
    DAIRY_FREE = "dairy_free"


class MacroPreference(StrEnum):
    """How the user likes calories split into macros (interpreted by targets)."""

    BALANCED = "balanced"
    HIGH_PROTEIN = "high_protein"
    LOW_CARB = "low_carb"


@dataclass(frozen=True, slots=True)
class Profile:
    user_id: UserId
    sex: Sex
    birth_date: date
    height_cm: Decimal
    weight_kg: Decimal
    activity_level: ActivityLevel
    goal: Goal
    dietary_preferences: frozenset[DietaryPreference]
    macro_preference: MacroPreference
    updated_at: datetime

    @classmethod
    def create(
        cls,
        *,
        user_id: UserId,
        sex: Sex,
        birth_date: date,
        height_cm: Decimal,
        weight_kg: Decimal,
        activity_level: ActivityLevel,
        goal: Goal,
        dietary_preferences: frozenset[DietaryPreference],
        today: date,
        now: datetime,
        macro_preference: MacroPreference = MacroPreference.BALANCED,
    ) -> "Profile":
        problems: list[str] = []

        age = _age_on(birth_date, today)
        if birth_date > today:
            problems.append("Birth date cannot be in the future.")
        elif not MIN_AGE_YEARS <= age <= MAX_AGE_YEARS:
            problems.append(f"Age must be between {MIN_AGE_YEARS} and {MAX_AGE_YEARS} years.")

        height = height_cm.quantize(_ONE_DECIMAL, ROUND_HALF_UP)
        if not HEIGHT_CM_RANGE[0] <= height <= HEIGHT_CM_RANGE[1]:
            problems.append(f"Height must be {HEIGHT_CM_RANGE[0]}-{HEIGHT_CM_RANGE[1]} cm.")

        weight = weight_kg.quantize(_ONE_DECIMAL, ROUND_HALF_UP)
        if not WEIGHT_KG_RANGE[0] <= weight <= WEIGHT_KG_RANGE[1]:
            problems.append(f"Weight must be {WEIGHT_KG_RANGE[0]}-{WEIGHT_KG_RANGE[1]} kg.")

        if problems:
            raise InvalidProfileError(" ".join(problems))

        return cls(
            user_id=user_id,
            sex=sex,
            birth_date=birth_date,
            height_cm=height,
            weight_kg=weight,
            activity_level=activity_level,
            goal=goal,
            dietary_preferences=dietary_preferences,
            macro_preference=macro_preference,
            updated_at=now,
        )

    def age_on(self, day: date) -> int:
        return _age_on(self.birth_date, day)


def _age_on(birth_date: date, day: date) -> int:
    had_birthday = (day.month, day.day) >= (birth_date.month, birth_date.day)
    return day.year - birth_date.year - (0 if had_birthday else 1)
