from dataclasses import dataclass
from datetime import date
from typing import Protocol

from nutritionist.core.clock import Clock
from nutritionist.core.exceptions import NotFoundError
from nutritionist.core.ids import UserId
from nutritionist.modules.targets.domain.calculator import TargetCalculator
from nutritionist.modules.targets.domain.models import BodyStats, MacroSplit, NutritionTargets


class ProfileRequiredError(NotFoundError):
    code = "profile_required"
    title = "A profile is required to compute targets"


class BodyStatsProvider(Protocol):
    """Where targets get body data from. Implemented outside this module
    (see ``nutritionist.interop``), so targets never imports profile."""

    async def for_user(self, user_id: UserId, on: date) -> BodyStats | None: ...


@dataclass(frozen=True, slots=True)
class GetTargets:
    body_stats: BodyStatsProvider
    calculator: TargetCalculator
    clock: Clock

    async def execute(
        self, user_id: UserId, split: MacroSplit | None = None, on: date | None = None
    ) -> NutritionTargets:
        """Targets for ``on`` (default: today), with the user's preferred split unless
        ``split`` overrides it."""
        stats = await self.body_stats.for_user(user_id, on or self.clock.today())
        if stats is None:
            raise ProfileRequiredError("Create your profile with PUT /me/profile first.")
        return self.calculator.calculate(stats, split or stats.preferred_split)
