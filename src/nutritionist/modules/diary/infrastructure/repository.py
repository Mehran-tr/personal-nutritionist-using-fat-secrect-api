from datetime import date

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nutritionist.core.db import SqlAlchemyUnitOfWork
from nutritionist.core.exceptions import AuthenticationError
from nutritionist.core.ids import UserId
from nutritionist.modules.diary.domain.models import (
    DayTargets,
    DiaryEntry,
    EntryId,
    LoggedFood,
    MealType,
    NutrientAmounts,
)
from nutritionist.modules.diary.infrastructure.orm import DayTargetsRecord, DiaryEntryRecord

_USER_FKS = ("fk_diary_entries_user_id_users", "fk_diary_day_targets_user_id_users")


class SqlAlchemyDiaryEntryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entry: DiaryEntry) -> None:
        self._session.add(DiaryEntryRecord(id=entry.id, **_columns(entry)))

    async def get(self, entry_id: EntryId) -> DiaryEntry | None:
        record = await self._session.get(DiaryEntryRecord, entry_id)
        return _to_domain(record) if record else None

    async def update(self, entry: DiaryEntry) -> None:
        await self._session.execute(
            update(DiaryEntryRecord)
            .where(DiaryEntryRecord.id == entry.id)
            .values(servings=entry.servings, meal=entry.meal.value)
        )

    async def delete(self, entry_id: EntryId) -> None:
        await self._session.execute(delete(DiaryEntryRecord).where(DiaryEntryRecord.id == entry_id))

    async def list_for_day(self, user_id: UserId, day: date) -> list[DiaryEntry]:
        records = await self._session.scalars(
            select(DiaryEntryRecord)
            .where(DiaryEntryRecord.user_id == user_id, DiaryEntryRecord.day == day)
            .order_by(DiaryEntryRecord.logged_at)
        )
        return [_to_domain(r) for r in records]

    async def count_for_day(self, user_id: UserId, day: date) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(DiaryEntryRecord)
            .where(DiaryEntryRecord.user_id == user_id, DiaryEntryRecord.day == day)
        )
        return int(count or 0)


class SqlAlchemyDayTargetsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UserId, day: date) -> DayTargets | None:
        record = await self._session.get(DayTargetsRecord, (user_id, day))
        if record is None:
            return None
        return DayTargets(
            calories_kcal=record.calories_kcal,
            protein_g=record.protein_g,
            carbohydrate_g=record.carbohydrate_g,
            fat_g=record.fat_g,
            fiber_g=record.fiber_g,
            macro_split=record.macro_split,
        )

    async def save_if_absent(self, user_id: UserId, day: date, targets: DayTargets) -> None:
        # ON CONFLICT DO NOTHING: two concurrent first logs of the day can't conflict.
        await self._session.execute(
            insert(DayTargetsRecord)
            .values(
                user_id=user_id,
                day=day,
                calories_kcal=targets.calories_kcal,
                protein_g=targets.protein_g,
                carbohydrate_g=targets.carbohydrate_g,
                fat_g=targets.fat_g,
                fiber_g=targets.fiber_g,
                macro_split=targets.macro_split,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "day"])
        )


class SqlAlchemyDiaryUnitOfWork(SqlAlchemyUnitOfWork):
    entries: SqlAlchemyDiaryEntryRepository
    day_targets: SqlAlchemyDayTargetsRepository

    def _bind_repositories(self, session: AsyncSession) -> None:
        self.entries = SqlAlchemyDiaryEntryRepository(session)
        self.day_targets = SqlAlchemyDayTargetsRepository(session)

    async def commit(self) -> None:
        try:
            await super().commit()
        except IntegrityError as exc:
            if any(fk in str(exc.orig) for fk in _USER_FKS):  # account deleted meanwhile
                raise AuthenticationError("Account no longer exists.") from exc
            raise


def _columns(entry: DiaryEntry) -> dict[str, object]:
    food, n = entry.food, entry.food.per_serving
    return {
        "user_id": entry.user_id,
        "day": entry.day,
        "meal": entry.meal.value,
        "servings": entry.servings,
        "logged_at": entry.logged_at,
        "provider": food.provider,
        "food_id": food.food_id,
        "food_name": food.food_name,
        "brand": food.brand,
        "serving_id": food.serving_id,
        "serving_description": food.serving_description,
        "calories_kcal": n.calories_kcal,
        "protein_g": n.protein_g,
        "carbohydrate_g": n.carbohydrate_g,
        "fat_g": n.fat_g,
        "fiber_g": n.fiber_g,
        "sugar_g": n.sugar_g,
        "saturated_fat_g": n.saturated_fat_g,
        "sodium_mg": n.sodium_mg,
    }


def _to_domain(r: DiaryEntryRecord) -> DiaryEntry:
    return DiaryEntry(
        id=r.id,
        user_id=UserId(r.user_id),
        day=r.day,
        meal=MealType(r.meal),
        servings=r.servings,
        logged_at=r.logged_at,
        food=LoggedFood(
            provider=r.provider,
            food_id=r.food_id,
            food_name=r.food_name,
            brand=r.brand,
            serving_id=r.serving_id,
            serving_description=r.serving_description,
            per_serving=NutrientAmounts(
                calories_kcal=r.calories_kcal,
                protein_g=r.protein_g,
                carbohydrate_g=r.carbohydrate_g,
                fat_g=r.fat_g,
                fiber_g=r.fiber_g,
                sugar_g=r.sugar_g,
                saturated_fat_g=r.saturated_fat_g,
                sodium_mg=r.sodium_mg,
            ),
        ),
    )
