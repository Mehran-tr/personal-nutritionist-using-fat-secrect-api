"""Cross-module adapter: the profile module, seen through the targets module's port.

Modules never import each other. When one needs another's data, a small adapter
here translates between their public application APIs. Only ``bootstrap`` imports
this package.
"""

from datetime import date

from nutritionist.core.ids import UserId
from nutritionist.modules.profile.application.use_cases import GetProfile
from nutritionist.modules.profile.domain.errors import ProfileNotFoundError
from nutritionist.modules.targets.domain.models import (
    ActivityLevel,
    BodyStats,
    Goal,
    MacroSplit,
    Sex,
)


class ProfileBodyStatsProvider:
    def __init__(self, get_profile: GetProfile) -> None:
        self._get_profile = get_profile

    async def for_user(self, user_id: UserId, on: date) -> BodyStats | None:
        try:
            profile = await self._get_profile.execute(user_id)
        except ProfileNotFoundError:
            return None
        return BodyStats(
            sex=Sex(profile.sex.value),
            age_years=profile.age_on(on),
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity_level=ActivityLevel(profile.activity_level.value),
            goal=Goal(profile.goal.value),
            preferred_split=MacroSplit(profile.macro_preference.value),
        )
