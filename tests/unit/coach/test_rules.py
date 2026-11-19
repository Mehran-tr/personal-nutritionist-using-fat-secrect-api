from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from nutritionist.modules.coach.domain.models import (
    CoachDay,
    DayStatus,
    Goals,
    InsightCode,
    Intake,
    Severity,
)
from nutritionist.modules.coach.domain.rules import CoachEngine

GOALS = Goals(calories_kcal=2000, protein_g=150, carbohydrate_g=200, fat_g=67, fiber_g=28)
ON_TARGET = Intake(
    calories_kcal=Decimal(2000),
    protein_g=Decimal(150),
    carbohydrate_g=Decimal(200),
    fat_g=Decimal(67),
    fiber_g=Decimal(30),
    saturated_fat_g=Decimal(15),
    sodium_mg=Decimal(1500),
)
engine = CoachEngine()


def day(
    status: DayStatus = DayStatus.COMPLETE,
    goals: Goals | None = GOALS,
    entries: int = 4,
    missing: dict[str, int] | None = None,
    **intake: Any,
) -> CoachDay:
    return CoachDay(
        day=date(2026, 11, 18),
        status=status,
        intake=replace(
            ON_TARGET, **{k: Decimal(v) if v is not None else None for k, v in intake.items()}
        ),
        goals=goals,
        entry_count=entries,
        entries_missing=missing or {},
    )


def codes(d: CoachDay) -> list[InsightCode]:
    return [i.code for i in engine.review(d)]


def test_a_good_day_is_on_track_and_nothing_else() -> None:
    assert codes(day()) == [InsightCode.ON_TRACK]


@pytest.mark.parametrize(
    ("intake", "expected"),
    [
        ({"calories_kcal": 2201}, InsightCode.CALORIES_OVER),
        ({"calories_kcal": 1599}, InsightCode.CALORIES_UNDER),
        ({"calories_kcal": 1199}, InsightCode.CALORIES_VERY_LOW),
        ({"protein_g": 134}, InsightCode.PROTEIN_UNDER),
        ({"fiber_g": 22}, InsightCode.FIBER_UNDER),
        ({"sodium_mg": 2301}, InsightCode.SODIUM_HIGH),
        ({"saturated_fat_g": 23}, InsightCode.SATURATED_FAT_HIGH),  # limit 2000*10%/9 = 22.2
    ],
)
def test_each_rule_fires_just_past_its_threshold(
    intake: dict[str, int], expected: InsightCode
) -> None:
    assert expected in codes(day(**intake))


@pytest.mark.parametrize(
    "intake",
    [
        {"calories_kcal": 2200},
        {"calories_kcal": 1800},
        {"protein_g": 135},
        {"fiber_g": "22.4"},
        {"sodium_mg": 2300},
    ],
)
def test_rules_stay_quiet_at_their_threshold(intake: dict[str, Any]) -> None:
    assert codes(day(**intake)) == [InsightCode.ON_TRACK]


def test_gap_between_under_and_on_track_stays_silent() -> None:
    assert codes(day(calories_kcal=1700)) == []


def test_very_low_intake_is_a_safety_warning_not_a_compliment() -> None:
    review = engine.review(day(calories_kcal=900, protein_g=40))
    first = review[0]
    assert first.code is InsightCode.CALORIES_VERY_LOW
    assert first.severity is Severity.WARNING
    assert "doctor or dietitian" in first.message
    assert InsightCode.CALORIES_UNDER not in [i.code for i in review]
    assert InsightCode.ON_TRACK not in [i.code for i in review]


def test_in_progress_day_only_warns_about_excess() -> None:
    lunchtime = day(
        DayStatus.IN_PROGRESS, calories_kcal=700, protein_g=20, fiber_g=3, sodium_mg=2600
    )
    assert codes(lunchtime) == [InsightCode.SODIUM_HIGH]


def test_warnings_come_first_then_rule_order_and_output_is_capped() -> None:
    bad = day(
        calories_kcal=2600,
        protein_g=50,
        fiber_g=5,
        sodium_mg=4000,
        saturated_fat_g=60,
        missing={"sugar": 2},
    )
    review = engine.review(bad)
    assert [i.severity for i in review] == sorted((i.severity for i in review), reverse=True)
    assert [i.code for i in review][:2] == [InsightCode.CALORIES_OVER, InsightCode.SODIUM_HIGH]
    assert len(review) == 5


def test_messages_carry_concrete_numbers() -> None:
    (insight,) = [
        i for i in engine.review(day(protein_g=110)) if i.code is InsightCode.PROTEIN_UNDER
    ]
    assert insight.message.startswith("Protein was 40 g below your 150 g target.")
    assert (insight.actual, insight.target, insight.unit) == (Decimal(110), Decimal(150), "g")


def test_nothing_logged() -> None:
    assert codes(day(entries=0, calories_kcal=0, protein_g=0)) == [InsightCode.NOTHING_LOGGED]
    today = engine.review(day(DayStatus.IN_PROGRESS, entries=0, calories_kcal=0))
    assert "yet today" in today[0].message


def test_without_targets_only_absolute_rules_apply() -> None:
    assert codes(day(goals=None, sodium_mg=3000)) == [
        InsightCode.SODIUM_HIGH,
        InsightCode.NO_TARGETS,
    ]


def test_unknown_values_never_trigger_rules_and_are_disclosed() -> None:
    unknown = day(fiber_g=None, sodium_mg=None, missing={"fiber": 3, "sodium": 1, "sugar": 0})
    review = engine.review(unknown)
    assert [i.code for i in review] == [InsightCode.ON_TRACK, InsightCode.INCOMPLETE_DATA]
    assert review[1].message.startswith("Some foods have no data for fiber, sodium")
