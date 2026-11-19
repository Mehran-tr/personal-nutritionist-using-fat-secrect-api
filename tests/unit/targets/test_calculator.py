"""Reference values are hand-computed from the published equations (shown inline),
so a refactor that silently changes the maths fails loudly."""

import itertools
from decimal import Decimal

import pytest

from nutritionist.modules.targets.domain.calculator import TargetCalculator
from nutritionist.modules.targets.domain.energy import CALORIE_FLOOR
from nutritionist.modules.targets.domain.models import (
    ActivityLevel,
    Adjustment,
    BodyStats,
    Goal,
    MacroSplit,
    Sex,
)

calculator = TargetCalculator()


def stats(
    sex: Sex = Sex.MALE,
    age: int = 30,
    height: str = "180",
    weight: str = "80",
    activity: ActivityLevel = ActivityLevel.MODERATE,
    goal: Goal = Goal.LOSE_WEIGHT,
) -> BodyStats:
    return BodyStats(sex, age, Decimal(height), Decimal(weight), activity, goal)


class TestEnergy:
    def test_reference_male_losing_weight(self) -> None:
        # BMR = 10*80 + 6.25*180 - 5*30 + 5 = 1780; TDEE = 1780 * 1.55 = 2759
        # deficit = min(500, 20% of 2759) = 500 -> 2259 -> 2260
        result = calculator.calculate(stats())
        assert (result.bmr_kcal, result.tdee_kcal, result.calories_kcal) == (1780, 2759, 2260)
        assert result.adjustments == ()
        assert result.formula == "mifflin_st_jeor"

    def test_maintain_is_tdee(self) -> None:
        assert calculator.calculate(stats(goal=Goal.MAINTAIN)).calories_kcal == 2760

    def test_surplus_is_capped_relative_to_tdee(self) -> None:
        # surplus = min(300, 10% of 2759 = 275.9) -> 3034.9 -> 3030
        result = calculator.calculate(stats(goal=Goal.GAIN_WEIGHT))
        assert result.calories_kcal == 3030
        assert result.adjustments == (Adjustment.SURPLUS_CAPPED,)

    def test_small_sedentary_woman_is_protected_by_floors(self) -> None:
        # BMR = 600 + 1031.25 - 125 - 161 = 1345.25; TDEE = 1614.3
        # deficit capped at 20% = 322.86 -> 1291.4, below max(1200, BMR) -> ceil to 1350
        result = calculator.calculate(
            stats(Sex.FEMALE, 25, "165", "60", ActivityLevel.SEDENTARY, Goal.LOSE_WEIGHT)
        )
        assert (result.bmr_kcal, result.calories_kcal) == (1345, 1350)
        assert result.adjustments == (
            Adjustment.DEFICIT_CAPPED,
            Adjustment.CALORIE_FLOOR_APPLIED,
        )


class TestMacros:
    def test_reference_balanced_split(self) -> None:
        # protein 1.6 g/kg * 80 = 128 g (512 kcal); fat 30% of 2260 = 678 kcal = 75 g;
        # carbs = (2260 - 512 - 678) / 4 = 267.5 -> 268 g; fiber = 14 g/1000 kcal = 32 g
        macros = calculator.calculate(stats()).macros
        assert (macros.protein_g, macros.fat_g, macros.carbohydrate_g, macros.fiber_g) == (
            128,
            75,
            268,
            32,
        )

    def test_low_carb_fixes_carbs_and_fat_takes_the_rest(self) -> None:
        # protein 1.8*80 = 144 g (576); carbs 20% = 452 kcal = 113 g; fat = 1232/9 = 137 g
        macros = calculator.calculate(stats(), MacroSplit.LOW_CARB).macros
        assert (macros.protein_g, macros.carbohydrate_g, macros.fat_g) == (144, 113, 137)

    def test_obesity_uses_reference_weight_for_protein(self) -> None:
        # BMI 120/1.75^2 = 39.2 -> weight at BMI 25 = 76.5625 kg -> 1.6 * 76.5625 = 122.5 -> 123 g
        result = calculator.calculate(stats(age=40, height="175", weight="120"))
        assert result.macros.protein_g == 123
        assert Adjustment.PROTEIN_BASED_ON_REFERENCE_WEIGHT in result.adjustments

    def test_protein_is_capped_at_35_percent_of_energy(self) -> None:
        # Target hits the 1200 floor; 2.2 g/kg * 50 = 110 g (440 kcal) > 35% (420) -> 105 g
        result = calculator.calculate(
            stats(Sex.FEMALE, 60, "155", "50", ActivityLevel.SEDENTARY, Goal.LOSE_WEIGHT),
            MacroSplit.HIGH_PROTEIN,
        )
        assert result.calories_kcal == 1200
        assert result.macros.protein_g == 105
        assert Adjustment.PROTEIN_CAPPED in result.adjustments


# A grid across the whole valid input space: the invariants must hold everywhere.
GRID = list(
    itertools.product(
        Sex,
        (18, 45, 100),
        ("100", "165", "250"),
        ("30", "70", "140", "300"),
        ActivityLevel,
        Goal,
        MacroSplit,
    )
)


@pytest.mark.parametrize(("sex", "age", "height", "weight", "activity", "goal", "split"), GRID)
def test_invariants(
    sex: Sex,
    age: int,
    height: str,
    weight: str,
    activity: ActivityLevel,
    goal: Goal,
    split: MacroSplit,
) -> None:
    body = stats(sex, age, height, weight, activity, goal)
    result = calculator.calculate(body, split)
    m = result.macros

    assert result.calories_kcal % 10 == 0
    assert result.calories_kcal >= CALORIE_FLOOR[sex]
    assert result.calories_kcal >= result.bmr_kcal
    assert min(m.protein_g, m.carbohydrate_g, m.fat_g, m.fiber_g) >= 0
    assert m.protein_g * 4 <= result.calories_kcal * Decimal("0.35") + 2

    macro_kcal = m.protein_g * 4 + m.carbohydrate_g * 4 + m.fat_g * 9
    assert abs(macro_kcal - result.calories_kcal) <= 10  # only rounding may differ
