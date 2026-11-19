from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from nutritionist.api.security import CurrentUserId
from nutritionist.modules.diary.api.schemas import (
    DaySummaryOut,
    EntryOut,
    LogFoodIn,
    UpdateEntryIn,
)
from nutritionist.modules.diary.application.use_cases import DiaryUseCases

router = APIRouter(prefix="/me/diary", tags=["diary"])


def _diary(request: Request) -> DiaryUseCases:
    use_cases: DiaryUseCases = request.app.state.container.diary
    return use_cases


Diary = Annotated[DiaryUseCases, Depends(_diary)]


@router.post(
    "/entries",
    response_model=EntryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Log a food (nutrients are looked up server-side)",
)
async def log_food(user_id: CurrentUserId, body: LogFoodIn, diary: Diary) -> EntryOut:
    return EntryOut.from_domain(await diary.log_food.execute(user_id, body.to_command()))


@router.patch("/entries/{entry_id}", response_model=EntryOut, summary="Change servings or meal")
async def update_entry(
    user_id: CurrentUserId, entry_id: UUID, body: UpdateEntryIn, diary: Diary
) -> EntryOut:
    entry = await diary.update_entry.execute(
        user_id, entry_id, servings=body.servings, meal=body.meal
    )
    return EntryOut.from_domain(entry)


@router.delete(
    "/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove an entry"
)
async def delete_entry(user_id: CurrentUserId, entry_id: UUID, diary: Diary) -> Response:
    await diary.delete_entry.execute(user_id, entry_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{day}", response_model=DaySummaryOut, summary="A day: entries, totals vs targets")
async def get_day(user_id: CurrentUserId, day: date, diary: Diary) -> DaySummaryOut:
    return DaySummaryOut.from_domain(await diary.get_daily_summary.execute(user_id, day))
