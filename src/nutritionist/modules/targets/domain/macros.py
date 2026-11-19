"""Macro allocation strategies.

Each strategy fixes protein per kg of body weight and fixes one more macro as a
share of energy. The last macro takes the remainder. Protein is capped at 35 %
of energy (the upper bound of the IOM's acceptable range), so with these shares
the remainder can never be negative.

References: IOM Dietary Reference Intakes (2005) AMDR; ISSN position stand on
protein (Jäger et al., 2017) for 1.4-2.2 g/kg in active people; fiber at
14 g per 1000 kcal (Dietary Guidelines for Americans).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from nutritionist.modules.targets.domain.models import (
    Adjustment,
    BodyStats,
    MacroSplit,
    MacroTargets,
)

KCAL_PER_G_PROTEIN = Decimal(4)
KCAL_PER_G_CARB = Decimal(4)
KCAL_PER_G_FAT = Decimal(9)
MAX_PROTEIN_SHARE = Decimal("0.35")
FIBER_G_PER_1000_KCAL = Decimal(14)
OBESITY_BMI = Decimal(30)
REFERENCE_BMI = Decimal(25)


class _Fixed(Enum):
    FAT = "fat"
    CARBS = "carbs"


@dataclass(frozen=True, slots=True)
class MacroStrategy:
    protein_g_per_kg: Decimal
    fixed: _Fixed
    fixed_share: Decimal  # share of total energy for the fixed macro


STRATEGIES: dict[MacroSplit, MacroStrategy] = {
    MacroSplit.BALANCED: MacroStrategy(Decimal("1.6"), _Fixed.FAT, Decimal("0.30")),
    MacroSplit.HIGH_PROTEIN: MacroStrategy(Decimal("2.2"), _Fixed.FAT, Decimal("0.25")),
    MacroSplit.LOW_CARB: MacroStrategy(Decimal("1.8"), _Fixed.CARBS, Decimal("0.20")),
}


@dataclass(frozen=True, slots=True)
class MacroResult:
    macros: MacroTargets
    adjustments: tuple[Adjustment, ...]


def protein_reference_weight(stats: BodyStats) -> tuple[Decimal, bool]:
    """With obesity, protein per kg of *total* weight overshoots: lean mass sets the
    need. Use the weight at BMI 25 for the same height instead."""
    if stats.bmi < OBESITY_BMI:
        return stats.weight_kg, False
    height_m = stats.height_cm / 100
    return REFERENCE_BMI * height_m * height_m, True


def allocate(stats: BodyStats, calories_kcal: int, split: MacroSplit) -> MacroResult:
    strategy = STRATEGIES[split]
    energy = Decimal(calories_kcal)
    adjustments: list[Adjustment] = []

    weight, adjusted = protein_reference_weight(stats)
    if adjusted:
        adjustments.append(Adjustment.PROTEIN_BASED_ON_REFERENCE_WEIGHT)

    protein_kcal = weight * strategy.protein_g_per_kg * KCAL_PER_G_PROTEIN
    if protein_kcal > energy * MAX_PROTEIN_SHARE:
        protein_kcal = energy * MAX_PROTEIN_SHARE
        adjustments.append(Adjustment.PROTEIN_CAPPED)

    fixed_kcal = energy * strategy.fixed_share
    remainder_kcal = energy - protein_kcal - fixed_kcal

    if strategy.fixed is _Fixed.FAT:
        fat_kcal, carb_kcal = fixed_kcal, remainder_kcal
    else:
        carb_kcal, fat_kcal = fixed_kcal, remainder_kcal

    return MacroResult(
        macros=MacroTargets(
            protein_g=_grams(protein_kcal / KCAL_PER_G_PROTEIN),
            carbohydrate_g=_grams(carb_kcal / KCAL_PER_G_CARB),
            fat_g=_grams(fat_kcal / KCAL_PER_G_FAT),
            fiber_g=_grams(energy / 1000 * FIBER_G_PER_1000_KCAL),
        ),
        adjustments=tuple(adjustments),
    )


def _grams(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
