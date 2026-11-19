"""Energy maths: BMR -> TDEE -> daily calorie target.

References
- Mifflin MD, St Jeor ST et al. (1990), Am J Clin Nutr 51:241-247. In reviews it is
  the most accurate of the common predictive equations for healthy adults.
- Activity factors: the conventional FAO/WHO-style multipliers used with it.
- Deficit/surplus: about 500 kcal/day (~0.5 kg/week) is the usual safe rate. We
  also cap it relative to TDEE so small or sedentary people aren't pushed too low.
- Floors: ~1200 kcal (women) / ~1500 kcal (men) are widely cited minimums
  without medical supervision. We also never go below the person's BMR.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Protocol

from nutritionist.modules.targets.domain.models import (
    ActivityLevel,
    Adjustment,
    BodyStats,
    Goal,
    Sex,
)

ACTIVITY_FACTORS: dict[ActivityLevel, Decimal] = {
    ActivityLevel.SEDENTARY: Decimal("1.2"),
    ActivityLevel.LIGHT: Decimal("1.375"),
    ActivityLevel.MODERATE: Decimal("1.55"),
    ActivityLevel.ACTIVE: Decimal("1.725"),
    ActivityLevel.VERY_ACTIVE: Decimal("1.9"),
}

MAX_DEFICIT_KCAL = Decimal(500)
MAX_DEFICIT_SHARE = Decimal("0.20")  # never more than 20 % below TDEE
MAX_SURPLUS_KCAL = Decimal(300)
MAX_SURPLUS_SHARE = Decimal("0.10")
CALORIE_FLOOR: dict[Sex, Decimal] = {Sex.FEMALE: Decimal(1200), Sex.MALE: Decimal(1500)}


class BmrFormula(Protocol):
    name: str

    def bmr(self, stats: BodyStats) -> Decimal: ...


class MifflinStJeor:
    name = "mifflin_st_jeor"

    def bmr(self, stats: BodyStats) -> Decimal:
        base = 10 * stats.weight_kg + Decimal("6.25") * stats.height_cm - 5 * stats.age_years
        return base + (5 if stats.sex is Sex.MALE else -161)


def tdee(bmr: Decimal, activity: ActivityLevel) -> Decimal:
    return bmr * ACTIVITY_FACTORS[activity]


@dataclass(frozen=True, slots=True)
class CalorieTarget:
    kcal: int
    adjustments: tuple[Adjustment, ...]


def calorie_target(stats: BodyStats, bmr: Decimal, tdee_kcal: Decimal) -> CalorieTarget:
    adjustments: list[Adjustment] = []

    match stats.goal:
        case Goal.LOSE_WEIGHT:
            deficit = min(MAX_DEFICIT_KCAL, tdee_kcal * MAX_DEFICIT_SHARE)
            if deficit < MAX_DEFICIT_KCAL:
                adjustments.append(Adjustment.DEFICIT_CAPPED)
            raw = tdee_kcal - deficit
        case Goal.GAIN_WEIGHT:
            surplus = min(MAX_SURPLUS_KCAL, tdee_kcal * MAX_SURPLUS_SHARE)
            if surplus < MAX_SURPLUS_KCAL:
                adjustments.append(Adjustment.SURPLUS_CAPPED)
            raw = tdee_kcal + surplus
        case Goal.MAINTAIN:
            raw = tdee_kcal

    floor = max(CALORIE_FLOOR[stats.sex], bmr)
    if raw < floor:
        adjustments.append(Adjustment.CALORIE_FLOOR_APPLIED)
        # Round *up* so rounding can never take us back below the floor.
        return CalorieTarget(_to_ten(floor, ROUND_CEILING), tuple(adjustments))
    return CalorieTarget(_to_ten(raw, ROUND_HALF_UP), tuple(adjustments))


def _to_ten(kcal: Decimal, rounding: str) -> int:
    """Targets are guidance: report them to the nearest 10 kcal, not false precision."""
    return int((kcal / 10).quantize(Decimal(1), rounding=rounding)) * 10
