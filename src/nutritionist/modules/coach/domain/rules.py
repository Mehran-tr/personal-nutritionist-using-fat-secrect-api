"""Coaching rules: small, independent, deterministic.

Each rule looks at one ``CoachDay`` and returns at most one ``Insight``. To add
coaching behaviour, add a rule and register it in ``DEFAULT_RULES``. Nothing
else changes.

Thresholds and sources
- Calories ±10 % of target counts as on target. Below 80 % on a complete day is
  "under", below 60 % is "very low" (a safety message, never praise).
- Protein below 90 % of target; fiber below 80 % (fiber data is often incomplete).
- Sodium above 2300 mg/day (Dietary Guidelines for Americans 2020-2025 upper limit).
- Saturated fat above 10 % of energy (DGA / WHO).
"Under target" and share-of-energy rules only run on COMPLETE days: at noon you
simply haven't eaten dinner yet. Absolute "over" rules run any time.
Between 80 % and 90 % of the calorie target nothing fires: close enough not to
nag, not close enough to call on track.
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from nutritionist.modules.coach.domain.models import (
    CoachDay,
    Insight,
    InsightCode,
    Severity,
)

CALORIES_OVER_RATIO = Decimal("1.10")
CALORIES_UNDER_RATIO = Decimal("0.80")
CALORIES_VERY_LOW_RATIO = Decimal("0.60")
ON_TRACK_TOLERANCE = Decimal("0.10")
PROTEIN_UNDER_RATIO = Decimal("0.90")
FIBER_UNDER_RATIO = Decimal("0.80")
SODIUM_LIMIT_MG = Decimal(2300)
SATURATED_FAT_MAX_ENERGY_SHARE = Decimal("0.10")
KCAL_PER_G_FAT = Decimal(9)


class Rule(Protocol):
    def evaluate(self, day: CoachDay) -> Insight | None: ...


def n(value: Decimal | int) -> int:
    """Whole numbers in messages: coaching, not lab reports."""
    return int(Decimal(value).quantize(Decimal(1), ROUND_HALF_UP))


class NothingLogged:
    def evaluate(self, day: CoachDay) -> Insight | None:
        if day.entry_count:
            return None
        message = (
            "Nothing was logged for this day, so there is nothing to review."
            if day.is_complete
            else "Nothing logged yet today. Log your meals to get feedback."
        )
        return Insight(InsightCode.NOTHING_LOGGED, Severity.INFO, message)


class NoTargets:
    def evaluate(self, day: CoachDay) -> Insight | None:
        if day.goals is not None or not day.entry_count:
            return None
        return Insight(
            InsightCode.NO_TARGETS,
            Severity.INFO,
            "Set up your profile to compare what you eat with personal targets.",
        )


class CaloriesOver:
    def evaluate(self, day: CoachDay) -> Insight | None:
        if day.goals is None:
            return None
        eaten, target = day.intake.calories_kcal, Decimal(day.goals.calories_kcal)
        if eaten <= target * CALORIES_OVER_RATIO:
            return None
        return Insight(
            InsightCode.CALORIES_OVER,
            Severity.WARNING,
            f"You're {n(eaten - target)} kcal over your {n(target)} kcal target.",
            "calories",
            eaten,
            target,
            "kcal",
        )


class CaloriesUnder:
    """Under target on a complete day. Very low intake gets a safety message instead."""

    def evaluate(self, day: CoachDay) -> Insight | None:
        if day.goals is None or not day.is_complete or not day.entry_count:
            return None
        eaten, target = day.intake.calories_kcal, Decimal(day.goals.calories_kcal)

        if eaten < target * CALORIES_VERY_LOW_RATIO:
            return Insight(
                InsightCode.CALORIES_VERY_LOW,
                Severity.WARNING,
                f"You logged {n(eaten)} kcal, far below your {n(target)} kcal target. "
                "If some meals weren't logged, no problem. Regularly eating this little "
                "isn't safe, so please talk to a doctor or dietitian if it's intentional.",
                "calories",
                eaten,
                target,
                "kcal",
            )
        if eaten < target * CALORIES_UNDER_RATIO:
            return Insight(
                InsightCode.CALORIES_UNDER,
                Severity.SUGGESTION,
                f"You were {n(target - eaten)} kcal under your {n(target)} kcal target.",
                "calories",
                eaten,
                target,
                "kcal",
            )
        return None


class ProteinUnder:
    def evaluate(self, day: CoachDay) -> Insight | None:
        if day.goals is None or not day.is_complete or not day.entry_count:
            return None
        eaten, target = day.intake.protein_g, Decimal(day.goals.protein_g)
        if eaten >= target * PROTEIN_UNDER_RATIO:
            return None
        return Insight(
            InsightCode.PROTEIN_UNDER,
            Severity.SUGGESTION,
            f"Protein was {n(target - eaten)} g below your {n(target)} g target. "
            "Eggs, yogurt, legumes, fish or tofu are easy additions.",
            "protein",
            eaten,
            target,
            "g",
        )


class FiberUnder:
    def evaluate(self, day: CoachDay) -> Insight | None:
        fiber = day.intake.fiber_g
        if day.goals is None or not day.is_complete or fiber is None:
            return None
        target = Decimal(day.goals.fiber_g)
        if fiber >= target * FIBER_UNDER_RATIO:
            return None
        return Insight(
            InsightCode.FIBER_UNDER,
            Severity.SUGGESTION,
            f"Fiber was {n(fiber)} g of your {n(target)} g target. "
            "Whole grains, beans, vegetables and fruit help.",
            "fiber",
            fiber,
            target,
            "g",
        )


class SodiumHigh:
    def evaluate(self, day: CoachDay) -> Insight | None:
        sodium = day.intake.sodium_mg
        if sodium is None or sodium <= SODIUM_LIMIT_MG:
            return None
        return Insight(
            InsightCode.SODIUM_HIGH,
            Severity.WARNING,
            f"Sodium reached {n(sodium)} mg, above the {n(SODIUM_LIMIT_MG)} mg daily limit.",
            "sodium",
            sodium,
            SODIUM_LIMIT_MG,
            "mg",
        )


class SaturatedFatHigh:
    def evaluate(self, day: CoachDay) -> Insight | None:
        saturated = day.intake.saturated_fat_g
        energy = day.intake.calories_kcal
        # A share of *today's* energy is noisy mid-day, so judge complete days only.
        if not day.is_complete or saturated is None or energy <= 0:
            return None
        limit_g = energy * SATURATED_FAT_MAX_ENERGY_SHARE / KCAL_PER_G_FAT
        if saturated <= limit_g:
            return None
        return Insight(
            InsightCode.SATURATED_FAT_HIGH,
            Severity.SUGGESTION,
            f"Saturated fat was {n(saturated)} g, above {n(limit_g)} g (10% of today's calories).",
            "saturated_fat",
            saturated,
            limit_g,
            "g",
        )


class OnTrack:
    def evaluate(self, day: CoachDay) -> Insight | None:
        if day.goals is None or not day.is_complete or not day.entry_count:
            return None
        target = Decimal(day.goals.calories_kcal)
        calories_ok = abs(day.intake.calories_kcal - target) <= target * ON_TRACK_TOLERANCE
        protein_ok = day.intake.protein_g >= day.goals.protein_g * PROTEIN_UNDER_RATIO
        if not (calories_ok and protein_ok):
            return None
        return Insight(
            InsightCode.ON_TRACK,
            Severity.INFO,
            "Calories and protein were on target.",
        )


class IncompleteData:
    """Be honest about what the numbers can't see."""

    def evaluate(self, day: CoachDay) -> Insight | None:
        missing = sorted(k for k, count in day.entries_missing.items() if count)
        if not missing:
            return None
        return Insight(
            InsightCode.INCOMPLETE_DATA,
            Severity.INFO,
            f"Some foods have no data for {', '.join(missing)}, so those totals are lower bounds.",
        )


DEFAULT_RULES: tuple[Rule, ...] = (
    NothingLogged(),
    NoTargets(),
    CaloriesOver(),
    CaloriesUnder(),
    ProteinUnder(),
    FiberUnder(),
    SodiumHigh(),
    SaturatedFatHigh(),
    OnTrack(),
    IncompleteData(),
)


class CoachEngine:
    """Runs every rule; returns insights by severity, then by rule order."""

    def __init__(self, rules: Sequence[Rule] = DEFAULT_RULES, max_insights: int = 5) -> None:
        self._rules = tuple(rules)
        self._max = max_insights

    def review(self, day: CoachDay) -> tuple[Insight, ...]:
        found = [(i, insight) for i, r in enumerate(self._rules) if (insight := r.evaluate(day))]
        found.sort(key=lambda pair: (-pair[1].severity, pair[0]))
        return tuple(insight for _, insight in found[: self._max])
