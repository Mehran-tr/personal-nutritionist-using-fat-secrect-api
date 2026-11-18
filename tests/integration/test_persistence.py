"""Repositories, units of work and migrations against a real PostgreSQL."""

from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from alembic import command
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nutritionist.core.db import create_session_factory
from nutritionist.core.exceptions import AuthenticationError
from nutritionist.core.ids import new_user_id
from nutritionist.modules.identity.domain.errors import EmailAlreadyRegisteredError
from nutritionist.modules.identity.domain.models import Email, User
from nutritionist.modules.identity.infrastructure.repository import SqlAlchemyIdentityUnitOfWork
from nutritionist.modules.profile.domain.models import (
    ActivityLevel,
    DietaryPreference,
    Goal,
    Profile,
    Sex,
)
from nutritionist.modules.profile.infrastructure.repository import SqlAlchemyProfileUnitOfWork
from tests.conftest import TEST_DATABASE_URL, alembic_config
from tests.fakes import NOW

pytestmark = pytest.mark.usefixtures("database")


@pytest.fixture
async def sessions() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    yield create_session_factory(engine)
    await engine.dispose()


def _user(email: str = "a@b.de") -> User:
    return User.register(Email(email), "hash", NOW)


def _profile(user: User, weight: str = "80.0") -> Profile:
    return Profile.create(
        user_id=user.id,
        sex=Sex.MALE,
        birth_date=date(1990, 1, 1),
        height_cm=Decimal("180"),
        weight_kg=Decimal(weight),
        activity_level=ActivityLevel.ACTIVE,
        goal=Goal.GAIN_WEIGHT,
        dietary_preferences=frozenset({DietaryPreference.VEGAN, DietaryPreference.GLUTEN_FREE}),
        today=NOW.date(),
        now=NOW,
    )


async def _add_user(sessions: async_sessionmaker[AsyncSession], user: User) -> None:
    async with SqlAlchemyIdentityUnitOfWork(sessions) as uow:
        uow.users.add(user)
        await uow.commit()


class TestUsers:
    async def test_round_trip(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        user = _user()
        await _add_user(sessions, user)

        async with SqlAlchemyIdentityUnitOfWork(sessions) as uow:
            assert await uow.users.get(user.id) == user
            assert await uow.users.get_by_email(Email("A@B.DE")) == user

    async def test_update(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        user = _user()
        await _add_user(sessions, user)

        async with SqlAlchemyIdentityUnitOfWork(sessions) as uow:
            await uow.users.update(replace(user, password_hash="new", is_active=False))
            await uow.commit()

        async with SqlAlchemyIdentityUnitOfWork(sessions) as uow:
            stored = await uow.users.get(user.id)
        assert stored is not None
        assert (stored.password_hash, stored.is_active) == ("new", False)

    async def test_nothing_persists_without_commit(
        self, sessions: async_sessionmaker[AsyncSession]
    ) -> None:
        user = _user()
        async with SqlAlchemyIdentityUnitOfWork(sessions) as uow:
            uow.users.add(user)

        async with SqlAlchemyIdentityUnitOfWork(sessions) as uow:
            assert await uow.users.get(user.id) is None

    async def test_concurrent_duplicate_signup_maps_to_domain_error(
        self, sessions: async_sessionmaker[AsyncSession]
    ) -> None:
        await _add_user(sessions, _user("a@b.de"))
        with pytest.raises(EmailAlreadyRegisteredError):
            await _add_user(sessions, _user("a@b.de"))


class TestProfiles:
    async def test_upsert_inserts_then_replaces(
        self, sessions: async_sessionmaker[AsyncSession]
    ) -> None:
        user = _user()
        await _add_user(sessions, user)

        for weight in ("80.0", "78.4"):
            async with SqlAlchemyProfileUnitOfWork(sessions) as uow:
                await uow.profiles.save(_profile(user, weight))
                await uow.commit()

        async with SqlAlchemyProfileUnitOfWork(sessions) as uow:
            stored = await uow.profiles.get(user.id)
        assert stored == _profile(user, "78.4")

    async def test_profile_for_missing_user_is_an_auth_error(
        self, sessions: async_sessionmaker[AsyncSession]
    ) -> None:
        orphan = replace(_user(), id=new_user_id())
        async with SqlAlchemyProfileUnitOfWork(sessions) as uow:
            with pytest.raises(AuthenticationError):
                await uow.profiles.save(_profile(orphan))


def test_models_and_migrations_are_in_sync() -> None:
    command.check(alembic_config())  # raises if autogenerate would produce changes


def test_migrations_downgrade_and_upgrade_cleanly() -> None:
    config = alembic_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")
