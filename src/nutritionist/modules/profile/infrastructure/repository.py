from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nutritionist.core.db import SqlAlchemyUnitOfWork
from nutritionist.core.exceptions import AuthenticationError
from nutritionist.core.ids import UserId
from nutritionist.modules.profile.domain.models import (
    ActivityLevel,
    DietaryPreference,
    Goal,
    Profile,
    Sex,
)
from nutritionist.modules.profile.infrastructure.orm import ProfileRecord

_USER_FK = "fk_profiles_user_id_users"


class SqlAlchemyProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId) -> Profile | None:
        record = await self._session.get(ProfileRecord, user_id)
        return _to_domain(record) if record else None

    async def save(self, profile: Profile) -> None:
        values = {
            "user_id": profile.user_id,
            "sex": profile.sex.value,
            "birth_date": profile.birth_date,
            "height_cm": profile.height_cm,
            "weight_kg": profile.weight_kg,
            "activity_level": profile.activity_level.value,
            "goal": profile.goal.value,
            "dietary_preferences": sorted(p.value for p in profile.dietary_preferences),
            "updated_at": profile.updated_at,
        }
        statement = insert(ProfileRecord).values(**values)
        # Atomic upsert: no read-then-write race between two PUTs.
        statement = statement.on_conflict_do_update(
            index_elements=[ProfileRecord.user_id],
            set_={k: statement.excluded[k] for k in values if k != "user_id"},
        )
        try:
            await self._session.execute(statement)  # runs now, not at commit
        except IntegrityError as exc:
            if _USER_FK in str(exc.orig):  # valid token, but the account was deleted
                raise AuthenticationError("Account no longer exists.") from exc
            raise


class SqlAlchemyProfileUnitOfWork(SqlAlchemyUnitOfWork):
    profiles: SqlAlchemyProfileRepository

    def _bind_repositories(self, session: AsyncSession) -> None:
        self.profiles = SqlAlchemyProfileRepository(session)


def _to_domain(record: ProfileRecord) -> Profile:
    return Profile(
        user_id=UserId(record.user_id),
        sex=Sex(record.sex),
        birth_date=record.birth_date,
        height_cm=record.height_cm,
        weight_kg=record.weight_kg,
        activity_level=ActivityLevel(record.activity_level),
        goal=Goal(record.goal),
        dietary_preferences=frozenset(DietaryPreference(p) for p in record.dietary_preferences),
        updated_at=record.updated_at,
    )
