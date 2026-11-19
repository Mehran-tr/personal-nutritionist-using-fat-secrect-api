from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from nutritionist.core.clock import Clock
from nutritionist.core.ids import UserId
from nutritionist.core.uow import UnitOfWork
from nutritionist.modules.diary.domain.errors import (
    DiaryEntryNotFoundError,
    FoodOrServingNotFoundError,
)
from nutritionist.modules.diary.domain.models import (
    DailySummary,
    DayTargets,
    DiaryEntry,
    EntryId,
    LoggedFood,
    MealType,
)
from nutritionist.modules.diary.domain.ports import DayTargetsRepository, DiaryEntryRepository

# ------------------------------------------------------------------ ports to other modules


class FoodLookup(Protocol):
    """Resolve a food + serving to what we store. Implemented on top of the catalog."""

    async def find(self, food_id: str, serving_id: str) -> LoggedFood | None: ...


class TargetsLookup(Protocol):
    """The user's targets for a day, or ``None`` if they cannot be computed yet."""

    async def for_day(self, user_id: UserId, day: date) -> DayTargets | None: ...


class DiaryUnitOfWork(UnitOfWork, Protocol):
    @property
    def entries(self) -> DiaryEntryRepository: ...

    @property
    def day_targets(self) -> DayTargetsRepository: ...


DiaryUowFactory = Callable[[], DiaryUnitOfWork]


# ------------------------------------------------------------------ use cases


@dataclass(frozen=True, slots=True)
class LogFoodCommand:
    day: date
    meal: MealType
    food_id: str
    serving_id: str
    servings: Decimal


@dataclass(frozen=True, slots=True)
class LogFood:
    uow: DiaryUowFactory
    foods: FoodLookup
    targets: TargetsLookup
    clock: Clock

    async def execute(self, user_id: UserId, command: LogFoodCommand) -> DiaryEntry:
        # Nutrients always come from our food source, never from the client.
        # The external lookup happens *before* the transaction opens, so a slow
        # upstream never holds a database connection.
        food = await self.foods.find(command.food_id, command.serving_id)
        if food is None:
            raise FoodOrServingNotFoundError(
                f"Food '{command.food_id}' has no serving '{command.serving_id}'."
            )
        entry = DiaryEntry.log(
            user_id=user_id,
            day=command.day,
            meal=command.meal,
            food=food,
            servings=command.servings,
            today=self.clock.today(),
            now=self.clock.now(),
        )
        day_targets = await self.targets.for_day(user_id, command.day)

        async with self.uow() as uow:
            uow.entries.add(entry)
            if day_targets is not None:
                # First write wins: later logs on the same day keep the original targets.
                await uow.day_targets.save_if_absent(user_id, command.day, day_targets)
            await uow.commit()
        return entry


@dataclass(frozen=True, slots=True)
class UpdateEntry:
    uow: DiaryUowFactory

    async def execute(
        self,
        user_id: UserId,
        entry_id: EntryId,
        *,
        servings: Decimal | None = None,
        meal: MealType | None = None,
    ) -> DiaryEntry:
        async with self.uow() as uow:
            entry = await _owned_entry(uow, user_id, entry_id)
            updated = entry.change(servings=servings, meal=meal)
            await uow.entries.update(updated)
            await uow.commit()
        return updated


@dataclass(frozen=True, slots=True)
class DeleteEntry:
    uow: DiaryUowFactory

    async def execute(self, user_id: UserId, entry_id: EntryId) -> None:
        async with self.uow() as uow:
            await _owned_entry(uow, user_id, entry_id)
            await uow.entries.delete(entry_id)
            await uow.commit()


@dataclass(frozen=True, slots=True)
class GetDailySummary:
    uow: DiaryUowFactory
    targets: TargetsLookup

    async def execute(self, user_id: UserId, day: date) -> DailySummary:
        async with self.uow() as uow:
            entries = await uow.entries.list_for_day(user_id, day)
            snapshot = await uow.day_targets.get(user_id, day)

        if snapshot is not None:
            return DailySummary.build(day, entries, snapshot, "snapshot")
        # No snapshot (nothing logged yet, or no profile back then): show what the
        # targets would be now, without persisting anything on a read.
        return DailySummary.build(day, entries, await self.targets.for_day(user_id, day), "current")


@dataclass(frozen=True, slots=True)
class DiaryUseCases:
    log_food: LogFood
    update_entry: UpdateEntry
    delete_entry: DeleteEntry
    get_daily_summary: GetDailySummary


async def _owned_entry(uow: DiaryUnitOfWork, user_id: UserId, entry_id: EntryId) -> DiaryEntry:
    entry = await uow.entries.get(entry_id)
    if entry is None or entry.user_id != user_id:
        raise DiaryEntryNotFoundError()
    return entry
