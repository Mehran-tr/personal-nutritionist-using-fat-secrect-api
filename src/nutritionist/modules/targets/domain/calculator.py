from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from nutritionist.modules.targets.domain.energy import (
    BmrFormula,
    MifflinStJeor,
    calorie_target,
    tdee,
)
from nutritionist.modules.targets.domain.macros import allocate
from nutritionist.modules.targets.domain.models import BodyStats, MacroSplit, NutritionTargets


@dataclass(frozen=True, slots=True)
class TargetCalculator:
    """Pure function object: same stats in, same targets out. No I/O, no clock."""

    formula: BmrFormula = field(default_factory=MifflinStJeor)

    def calculate(
        self, stats: BodyStats, split: MacroSplit = MacroSplit.BALANCED
    ) -> NutritionTargets:
        bmr = self.formula.bmr(stats)
        tdee_kcal = tdee(bmr, stats.activity_level)
        calories = calorie_target(stats, bmr, tdee_kcal)
        macros = allocate(stats, calories.kcal, split)

        return NutritionTargets(
            formula=self.formula.name,
            macro_split=split,
            bmr_kcal=_kcal(bmr),
            tdee_kcal=_kcal(tdee_kcal),
            calories_kcal=calories.kcal,
            macros=macros.macros,
            adjustments=calories.adjustments + macros.adjustments,
        )


def _kcal(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
