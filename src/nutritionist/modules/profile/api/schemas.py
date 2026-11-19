from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer

from nutritionist.modules.profile.application.use_cases import ProfileData
from nutritionist.modules.profile.domain.models import (
    ActivityLevel,
    DietaryPreference,
    Goal,
    MacroPreference,
    Profile,
    Sex,
)

Num = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class ProfileIn(BaseModel):
    sex: Sex
    birth_date: date
    height_cm: Decimal = Field(gt=0, lt=1000, examples=[178.0])
    weight_kg: Decimal = Field(gt=0, lt=1000, examples=[82.5])
    activity_level: ActivityLevel
    goal: Goal
    dietary_preferences: set[DietaryPreference] = Field(default_factory=set)
    macro_preference: MacroPreference = MacroPreference.BALANCED

    def to_command(self) -> ProfileData:
        return ProfileData(
            sex=self.sex,
            birth_date=self.birth_date,
            height_cm=self.height_cm,
            weight_kg=self.weight_kg,
            activity_level=self.activity_level,
            goal=self.goal,
            dietary_preferences=frozenset(self.dietary_preferences),
            macro_preference=self.macro_preference,
        )


class ProfileOut(BaseModel):
    sex: Sex
    birth_date: date
    height_cm: Num
    weight_kg: Num
    activity_level: ActivityLevel
    goal: Goal
    dietary_preferences: list[DietaryPreference]
    macro_preference: MacroPreference
    updated_at: datetime

    @classmethod
    def from_domain(cls, profile: Profile) -> "ProfileOut":
        return cls(
            sex=profile.sex,
            birth_date=profile.birth_date,
            height_cm=profile.height_cm,
            weight_kg=profile.weight_kg,
            activity_level=profile.activity_level,
            goal=profile.goal,
            dietary_preferences=sorted(profile.dietary_preferences),
            macro_preference=profile.macro_preference,
            updated_at=profile.updated_at,
        )
