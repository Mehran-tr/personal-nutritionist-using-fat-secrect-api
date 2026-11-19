from datetime import date
from typing import Protocol

from nutritionist.core.ids import UserId
from nutritionist.modules.diary.domain.models import DayTargets, DiaryEntry, EntryId


class DiaryEntryRepository(Protocol):
    def add(self, entry: DiaryEntry) -> None: ...

    async def get(self, entry_id: EntryId) -> DiaryEntry | None: ...

    async def update(self, entry: DiaryEntry) -> None: ...

    async def delete(self, entry_id: EntryId) -> None: ...

    async def list_for_day(self, user_id: UserId, day: date) -> list[DiaryEntry]: ...


class DayTargetsRepository(Protocol):
    """The targets that applied on a day, frozen when the day's first entry is logged."""

    async def get(self, user_id: UserId, day: date) -> DayTargets | None: ...

    async def save_if_absent(self, user_id: UserId, day: date, targets: DayTargets) -> None: ...
