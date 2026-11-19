from datetime import date
from decimal import Decimal
from types import TracebackType
from typing import Self

from nutritionist.core.ids import UserId
from nutritionist.modules.diary.domain.models import (
    DayTargets,
    DiaryEntry,
    EntryId,
    LoggedFood,
    NutrientAmounts,
)

OATS = LoggedFood(
    provider="fake",
    food_id="10",
    food_name="Oats",
    serving_id="s40",
    serving_description="40 g",
    per_serving=NutrientAmounts(
        Decimal("150"), Decimal("5"), Decimal("27"), Decimal("2.5"), fiber_g=Decimal("4")
    ),
)
TARGETS = DayTargets(2000, 150, 200, 67, 28, "balanced")


class FakeEntries:
    def __init__(self) -> None:
        self.rows: dict[EntryId, DiaryEntry] = {}

    def add(self, entry: DiaryEntry) -> None:
        self.rows[entry.id] = entry

    async def get(self, entry_id: EntryId) -> DiaryEntry | None:
        return self.rows.get(entry_id)

    async def update(self, entry: DiaryEntry) -> None:
        self.rows[entry.id] = entry

    async def delete(self, entry_id: EntryId) -> None:
        self.rows.pop(entry_id, None)

    async def list_for_day(self, user_id: UserId, day: date) -> list[DiaryEntry]:
        return [e for e in self.rows.values() if e.user_id == user_id and e.day == day]


class FakeDayTargets:
    def __init__(self) -> None:
        self.rows: dict[tuple[UserId, date], DayTargets] = {}

    async def get(self, user_id: UserId, day: date) -> DayTargets | None:
        return self.rows.get((user_id, day))

    async def save_if_absent(self, user_id: UserId, day: date, targets: DayTargets) -> None:
        self.rows.setdefault((user_id, day), targets)


class FakeDiaryUow:
    def __init__(self) -> None:
        self.entries = FakeEntries()
        self.day_targets = FakeDayTargets()
        self.commits = 0

    def __call__(self) -> Self:
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class FakeFoods:
    def __init__(self, *foods: LoggedFood) -> None:
        self._foods = {(f.food_id, f.serving_id): f for f in foods}

    async def find(self, food_id: str, serving_id: str) -> LoggedFood | None:
        return self._foods.get((food_id, serving_id))


class FakeTargets:
    def __init__(self, targets: DayTargets | None = TARGETS) -> None:
        self.targets = targets

    async def for_day(self, user_id: UserId, day: date) -> DayTargets | None:
        return self.targets
