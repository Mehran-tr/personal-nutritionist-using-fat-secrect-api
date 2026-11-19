"""Diary seen through the coach's ``DaySource`` port."""

from dataclasses import fields
from datetime import date

from nutritionist.core.ids import UserId
from nutritionist.modules.coach.domain.models import CoachDay, DayStatus, Goals, Intake
from nutritionist.modules.diary.application.use_cases import GetDailySummary
from nutritionist.modules.diary.domain.models import NutrientAmounts

_OPTIONAL_NUTRIENTS = {
    f.name: f.name.rsplit("_", 1)[0].replace("_", " ")  # "saturated_fat_g" -> "saturated fat"
    for f in fields(NutrientAmounts)
    if f.default is None
}


class DiaryDaySource:
    def __init__(self, get_summary: GetDailySummary) -> None:
        self._get_summary = get_summary

    async def for_day(self, user_id: UserId, day: date, today: date) -> CoachDay:
        summary = await self._get_summary.execute(user_id, day)
        t, g = summary.totals, summary.targets

        missing = {
            label: sum(1 for e in summary.entries if getattr(e.food.per_serving, attr) is None)
            for attr, label in _OPTIONAL_NUTRIENTS.items()
        }
        return CoachDay(
            day=day,
            status=DayStatus.COMPLETE if day < today else DayStatus.IN_PROGRESS,
            intake=Intake(
                calories_kcal=t.calories_kcal,
                protein_g=t.protein_g,
                carbohydrate_g=t.carbohydrate_g,
                fat_g=t.fat_g,
                fiber_g=t.fiber_g,
                sugar_g=t.sugar_g,
                saturated_fat_g=t.saturated_fat_g,
                sodium_mg=t.sodium_mg,
            ),
            goals=Goals(g.calories_kcal, g.protein_g, g.carbohydrate_g, g.fat_g, g.fiber_g)
            if g
            else None,
            entry_count=len(summary.entries),
            entries_missing=missing,
        )
