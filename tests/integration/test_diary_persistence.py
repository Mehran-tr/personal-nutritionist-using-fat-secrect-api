from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nutritionist.core.db import create_session_factory
from nutritionist.modules.diary.domain.models import DiaryEntry, MealType
from nutritionist.modules.diary.infrastructure.repository import SqlAlchemyDiaryUnitOfWork
from nutritionist.modules.identity.domain.models import Email, User
from nutritionist.modules.identity.infrastructure.repository import SqlAlchemyIdentityUnitOfWork
from tests.conftest import TEST_DATABASE_URL
from tests.fakes import NOW
from tests.unit.diary.fakes import OATS, TARGETS

pytestmark = pytest.mark.usefixtures("database")
TODAY = NOW.date()


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def user(sessions: async_sessionmaker[AsyncSession]) -> User:
    user = User.register(Email("d@b.de"), "hash", NOW)
    async with SqlAlchemyIdentityUnitOfWork(sessions) as uow:
        uow.users.add(user)
        await uow.commit()
    return user


def _entry(user: User, meal: MealType = MealType.LUNCH, days_ago: int = 0) -> DiaryEntry:
    return DiaryEntry.log(
        user_id=user.id,
        day=TODAY - timedelta(days=days_ago),
        meal=meal,
        food=replace(OATS, brand="Brand & Co"),
        servings=Decimal("1.5"),
        today=TODAY,
        now=NOW,
    )


async def test_entry_round_trip_preserves_the_snapshot_exactly(
    sessions: async_sessionmaker[AsyncSession], user: User
) -> None:
    entry = _entry(user)
    async with SqlAlchemyDiaryUnitOfWork(sessions) as uow:
        uow.entries.add(entry)
        await uow.commit()

    async with SqlAlchemyDiaryUnitOfWork(sessions) as uow:
        stored = await uow.entries.get(entry.id)
    assert stored == entry


async def test_list_for_day_update_and_delete(
    sessions: async_sessionmaker[AsyncSession], user: User
) -> None:
    today_a, today_b, yesterday = (
        _entry(user),
        _entry(user, MealType.DINNER),
        _entry(user, days_ago=1),
    )
    async with SqlAlchemyDiaryUnitOfWork(sessions) as uow:
        for e in (today_a, today_b, yesterday):
            uow.entries.add(e)
        await uow.commit()

    async with SqlAlchemyDiaryUnitOfWork(sessions) as uow:
        await uow.entries.update(today_a.change(servings=Decimal(3), meal=MealType.SNACK))
        await uow.entries.delete(today_b.id)
        await uow.commit()

    async with SqlAlchemyDiaryUnitOfWork(sessions) as uow:
        (only,) = await uow.entries.list_for_day(user.id, TODAY)
    assert (only.id, only.servings, only.meal) == (today_a.id, Decimal(3), MealType.SNACK)


async def test_day_targets_first_write_wins(
    sessions: async_sessionmaker[AsyncSession], user: User
) -> None:
    for calories in (2000, 1500):
        async with SqlAlchemyDiaryUnitOfWork(sessions) as uow:
            await uow.day_targets.save_if_absent(
                user.id, TODAY, replace(TARGETS, calories_kcal=calories)
            )
            await uow.commit()

    async with SqlAlchemyDiaryUnitOfWork(sessions) as uow:
        assert await uow.day_targets.get(user.id, TODAY) == TARGETS
        assert await uow.day_targets.get(user.id, TODAY - timedelta(days=1)) is None
