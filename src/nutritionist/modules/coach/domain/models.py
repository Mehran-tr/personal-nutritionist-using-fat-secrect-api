"""Coach vocabulary: what the coach knows about a day, and what it says about it.

Like targets, the coach has its own types. ``nutritionist.interop`` maps a diary
summary into a ``CoachDay``, so the diary can evolve freely.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import IntEnum, StrEnum


class DayStatus(StrEnum):
    IN_PROGRESS = "in_progress"  # today: "under target" just means "not eaten yet"
    COMPLETE = "complete"


class Severity(IntEnum):
    """Higher sorts first."""

    INFO = 1
    SUGGESTION = 2
    WARNING = 3


class InsightCode(StrEnum):
    NOTHING_LOGGED = "nothing_logged"
    CALORIES_OVER = "calories_over"
    CALORIES_UNDER = "calories_under"
    CALORIES_VERY_LOW = "calories_very_low"
    PROTEIN_UNDER = "protein_under"
    FIBER_UNDER = "fiber_under"
    SODIUM_HIGH = "sodium_high"
    SATURATED_FAT_HIGH = "saturated_fat_high"
    ON_TRACK = "on_track"
    INCOMPLETE_DATA = "incomplete_data"
    NO_TARGETS = "no_targets"


@dataclass(frozen=True, slots=True)
class Intake:
    calories_kcal: Decimal
    protein_g: Decimal
    carbohydrate_g: Decimal
    fat_g: Decimal
    fiber_g: Decimal | None = None
    sugar_g: Decimal | None = None
    saturated_fat_g: Decimal | None = None
    sodium_mg: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Goals:
    calories_kcal: int
    protein_g: int
    carbohydrate_g: int
    fat_g: int
    fiber_g: int


@dataclass(frozen=True, slots=True)
class CoachDay:
    day: date
    status: DayStatus
    intake: Intake
    goals: Goals | None
    entry_count: int
    # nutrient name -> number of entries whose food didn't report it
    entries_missing: Mapping[str, int] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return self.status is DayStatus.COMPLETE


@dataclass(frozen=True, slots=True)
class Insight:
    code: InsightCode
    severity: Severity
    message: str
    nutrient: str | None = None
    actual: Decimal | None = None
    target: Decimal | None = None
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class DayReview:
    day: date
    status: DayStatus
    insights: tuple[Insight, ...]
    summary: str | None = None  # natural-language version, only if an LLM is enabled
