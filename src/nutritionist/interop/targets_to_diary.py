"""Targets seen through the diary's ``TargetsLookup`` port."""

from datetime import date

from nutritionist.core.ids import UserId
from nutritionist.modules.diary.domain.models import DayTargets
from nutritionist.modules.targets.application.use_cases import GetTargets, ProfileRequiredError


class TargetsForDiary:
    def __init__(self, get_targets: GetTargets) -> None:
        self._get_targets = get_targets

    async def for_day(self, user_id: UserId, day: date) -> DayTargets | None:
        try:
            targets = await self._get_targets.execute(user_id, on=day)
        except ProfileRequiredError:
            return None  # logging food must work even before a profile exists
        m = targets.macros
        return DayTargets(
            calories_kcal=targets.calories_kcal,
            protein_g=m.protein_g,
            carbohydrate_g=m.carbohydrate_g,
            fat_g=m.fat_g,
            fiber_g=m.fiber_g,
            macro_split=targets.macro_split.value,
        )
