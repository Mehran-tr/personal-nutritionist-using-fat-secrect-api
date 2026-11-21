from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, PlainSerializer

from nutritionist.api.security import CurrentUserId
from nutritionist.modules.coach.application.use_cases import GetDayReview
from nutritionist.modules.coach.domain.models import DayReview, DayStatus, Insight, InsightCode

router = APIRouter(prefix="/me/coach", tags=["coach"])

Amount = Annotated[
    Decimal, PlainSerializer(lambda v: round(float(v), 1), return_type=float, when_used="json")
]


class InsightOut(BaseModel):
    code: InsightCode
    severity: str = Field(examples=["warning", "suggestion", "info"])
    message: str
    nutrient: str | None
    actual: Amount | None
    target: Amount | None
    unit: str | None

    @classmethod
    def from_domain(cls, i: Insight) -> "InsightOut":
        return cls(
            code=i.code,
            severity=i.severity.name.lower(),
            message=i.message,
            nutrient=i.nutrient,
            actual=i.actual,
            target=i.target,
            unit=i.unit,
        )


class DayReviewOut(BaseModel):
    day: date
    status: DayStatus
    insights: list[InsightOut] = Field(description="Most important first.")
    summary: str | None = Field(
        description="Friendly paragraph written by an LLM from the insights. "
        "null when LLM phrasing is disabled, unavailable or still pending."
    )
    summary_pending: bool = Field(
        description="True while the summary is generated in the background. "
        "Request the review again in a few seconds to get it."
    )

    @classmethod
    def from_domain(cls, r: DayReview) -> "DayReviewOut":
        return cls(
            day=r.day,
            status=r.status,
            insights=[InsightOut.from_domain(i) for i in r.insights],
            summary=r.summary,
            summary_pending=r.summary_pending,
        )


def _review(request: Request) -> GetDayReview:
    use_case: GetDayReview = request.app.state.container.coach
    return use_case


@router.get("/{day}", response_model=DayReviewOut, summary="Feedback on a diary day")
async def review_day(
    user_id: CurrentUserId,
    day: date,
    use_case: Annotated[GetDayReview, Depends(_review)],
) -> DayReviewOut:
    return DayReviewOut.from_domain(await use_case.execute(user_id, day))
