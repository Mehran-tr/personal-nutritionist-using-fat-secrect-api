from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from nutritionist.core.clock import FixedClock
from nutritionist.core.ids import new_user_id
from nutritionist.modules.profile.application.use_cases import GetProfile, ProfileData, SaveProfile
from nutritionist.modules.profile.domain.errors import InvalidProfileError, ProfileNotFoundError
from nutritionist.modules.profile.domain.models import (
    ActivityLevel,
    DietaryPreference,
    Goal,
    Profile,
    Sex,
)
from tests.fakes import NOW, FakeUnitOfWork

TODAY = NOW.date()  # 2026-11-17


def _create(**overrides: Any) -> Profile:
    values: dict[str, Any] = {
        "user_id": new_user_id(),
        "sex": Sex.MALE,
        "birth_date": date(1990, 5, 1),
        "height_cm": Decimal("178"),
        "weight_kg": Decimal("82.46"),
        "activity_level": ActivityLevel.MODERATE,
        "goal": Goal.LOSE_WEIGHT,
        "dietary_preferences": frozenset({DietaryPreference.HALAL}),
        "today": TODAY,
        "now": NOW,
    } | overrides
    return Profile.create(**values)


class TestProfileRules:
    def test_valid_profile_is_normalised(self) -> None:
        profile = _create()
        assert profile.weight_kg == Decimal("82.5")  # one decimal, half-up
        assert profile.age_on(TODAY) == 36

    @pytest.mark.parametrize(
        ("birth_date", "age"),
        [(date(2008, 11, 17), 18), (date(2008, 11, 18), 17), (date(2000, 2, 29), 26)],
    )
    def test_age_counts_birthdays_exactly(self, birth_date: date, age: int) -> None:
        if age < 18:
            with pytest.raises(InvalidProfileError, match="Age"):
                _create(birth_date=birth_date)
        else:
            assert _create(birth_date=birth_date).age_on(TODAY) == age

    @pytest.mark.parametrize(
        ("overrides", "message"),
        [
            ({"birth_date": date(2027, 1, 1)}, "future"),
            ({"birth_date": date(1900, 1, 1)}, "Age"),
            ({"height_cm": Decimal("99.9")}, "Height"),
            ({"weight_kg": Decimal("300.1")}, "Weight"),
        ],
    )
    def test_out_of_range_values(self, overrides: dict[str, Any], message: str) -> None:
        with pytest.raises(InvalidProfileError, match=message):
            _create(**overrides)

    def test_all_problems_are_reported_at_once(self) -> None:
        with pytest.raises(InvalidProfileError) as exc_info:
            _create(height_cm=Decimal(50), weight_kg=Decimal(10))
        assert "Height" in exc_info.value.detail
        assert "Weight" in exc_info.value.detail


class TestProfileUseCases:
    async def test_save_then_get(self) -> None:
        uow = FakeUnitOfWork()
        user_id = new_user_id()
        data = ProfileData(
            sex=Sex.FEMALE,
            birth_date=date(1995, 3, 2),
            height_cm=Decimal("165"),
            weight_kg=Decimal("60"),
            activity_level=ActivityLevel.LIGHT,
            goal=Goal.MAINTAIN,
        )

        saved = await SaveProfile(uow, FixedClock(NOW)).execute(user_id, data)

        assert await GetProfile(uow).execute(user_id) == saved
        assert saved.updated_at == NOW
        assert uow.commits == 1

    async def test_missing_profile(self) -> None:
        with pytest.raises(ProfileNotFoundError):
            await GetProfile(FakeUnitOfWork()).execute(new_user_id())
