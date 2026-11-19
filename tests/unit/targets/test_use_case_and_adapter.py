from datetime import date
from decimal import Decimal

import pytest

from nutritionist.core.clock import FixedClock
from nutritionist.core.ids import UserId, new_user_id
from nutritionist.interop.profile_to_targets import ProfileBodyStatsProvider
from nutritionist.modules.profile.application.use_cases import GetProfile, ProfileData, SaveProfile
from nutritionist.modules.profile.domain import models as profile
from nutritionist.modules.targets.application.use_cases import GetTargets, ProfileRequiredError
from nutritionist.modules.targets.domain.calculator import TargetCalculator
from nutritionist.modules.targets.domain.models import (
    ActivityLevel,
    BodyStats,
    Goal,
    MacroSplit,
    Sex,
)
from tests.fakes import NOW, FakeUnitOfWork


class NoProfile:
    async def for_user(self, user_id: UserId, on: date) -> BodyStats | None:
        return None


async def test_targets_need_a_profile() -> None:
    use_case = GetTargets(NoProfile(), TargetCalculator(), FixedClock(NOW))
    with pytest.raises(ProfileRequiredError):
        await use_case.execute(new_user_id())


async def test_profile_adapter_maps_vocabulary_and_age_on_the_given_day() -> None:
    uow = FakeUnitOfWork()
    user_id = new_user_id()
    await SaveProfile(uow, FixedClock(NOW)).execute(
        user_id,
        ProfileData(
            sex=profile.Sex.FEMALE,
            birth_date=date(1990, 11, 18),  # turns 36 the day after NOW
            height_cm=Decimal("170"),
            weight_kg=Decimal("65"),
            activity_level=profile.ActivityLevel.VERY_ACTIVE,
            goal=profile.Goal.GAIN_WEIGHT,
        ),
    )
    provider = ProfileBodyStatsProvider(GetProfile(uow))

    stats = await provider.for_user(user_id, NOW.date())

    assert stats == BodyStats(
        Sex.FEMALE,
        35,
        Decimal("170.0"),
        Decimal("65.0"),
        ActivityLevel.VERY_ACTIVE,
        Goal.GAIN_WEIGHT,
    )
    assert await provider.for_user(new_user_id(), NOW.date()) is None


@pytest.mark.parametrize(
    "enum_pair", [(profile.Sex, Sex), (profile.ActivityLevel, ActivityLevel), (profile.Goal, Goal)]
)
def test_every_profile_value_has_a_targets_counterpart(enum_pair: tuple[type, type]) -> None:
    # Guards the anti-corruption mapping: adding e.g. a new Goal to profile must
    # force a decision here instead of a runtime ValueError.
    source, target = enum_pair
    assert {m.value for m in source} == {m.value for m in target}


async def test_split_is_passed_through() -> None:
    class OneProfile:
        async def for_user(self, user_id: UserId, on: date) -> BodyStats | None:
            return BodyStats(
                Sex.MALE, 30, Decimal(180), Decimal(80), ActivityLevel.LIGHT, Goal.MAINTAIN
            )

    result = await GetTargets(OneProfile(), TargetCalculator(), FixedClock(NOW)).execute(
        new_user_id(), MacroSplit.HIGH_PROTEIN
    )
    assert result.macro_split is MacroSplit.HIGH_PROTEIN
