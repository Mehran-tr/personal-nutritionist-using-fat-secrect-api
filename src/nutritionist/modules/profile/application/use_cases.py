from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from nutritionist.core.clock import Clock
from nutritionist.core.ids import UserId
from nutritionist.core.uow import UnitOfWork
from nutritionist.modules.profile.domain.errors import ProfileNotFoundError
from nutritionist.modules.profile.domain.models import (
    ActivityLevel,
    DietaryPreference,
    Goal,
    Profile,
    Sex,
)
from nutritionist.modules.profile.domain.ports import ProfileRepository


class ProfileUnitOfWork(UnitOfWork, Protocol):
    @property
    def profiles(self) -> ProfileRepository: ...


ProfileUowFactory = Callable[[], ProfileUnitOfWork]


@dataclass(frozen=True, slots=True)
class ProfileData:
    """Input command for creating or replacing a profile."""

    sex: Sex
    birth_date: date
    height_cm: Decimal
    weight_kg: Decimal
    activity_level: ActivityLevel
    goal: Goal
    dietary_preferences: frozenset[DietaryPreference] = frozenset()


@dataclass(frozen=True, slots=True)
class SaveProfile:
    uow: ProfileUowFactory
    clock: Clock

    async def execute(self, user_id: UserId, data: ProfileData) -> Profile:
        profile = Profile.create(
            user_id=user_id,
            sex=data.sex,
            birth_date=data.birth_date,
            height_cm=data.height_cm,
            weight_kg=data.weight_kg,
            activity_level=data.activity_level,
            goal=data.goal,
            dietary_preferences=data.dietary_preferences,
            today=self.clock.today(),
            now=self.clock.now(),
        )
        async with self.uow() as uow:
            await uow.profiles.save(profile)
            await uow.commit()
        return profile


@dataclass(frozen=True, slots=True)
class GetProfile:
    uow: ProfileUowFactory

    async def execute(self, user_id: UserId) -> Profile:
        async with self.uow() as uow:
            profile = await uow.profiles.get(user_id)
        if profile is None:
            raise ProfileNotFoundError("Create your profile with PUT /me/profile first.")
        return profile


@dataclass(frozen=True, slots=True)
class ProfileUseCases:
    save_profile: SaveProfile
    get_profile: GetProfile
