from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from nutritionist.core.cache import InMemoryCache
from nutritionist.integrations.anthropic.client import AnthropicClient
from nutritionist.modules.coach.domain.models import (
    CoachDay,
    DayStatus,
    Insight,
    InsightCode,
    Intake,
    Severity,
)
from nutritionist.modules.coach.infrastructure.phrasers import (
    SYSTEM_PROMPT,
    CachedPhraser,
    LlmPhraser,
)

URL = "https://api.test/v1/messages"
DAY = CoachDay(
    date(2026, 11, 18),
    DayStatus.COMPLETE,
    Intake(Decimal(1800), Decimal(110), Decimal(200), Decimal(60)),
    None,
    3,
)
INSIGHTS = (
    Insight(
        InsightCode.SODIUM_HIGH,
        Severity.WARNING,
        "Sodium reached 2950 mg, above the 2300 mg daily limit.",
    ),
    Insight(
        InsightCode.PROTEIN_UNDER, Severity.SUGGESTION, "Protein was 40 g below your 150 g target."
    ),
)


def _phraser() -> LlmPhraser:
    client = AnthropicClient(httpx.AsyncClient(), api_key="sk-test", base_url="https://api.test")
    return LlmPhraser(client, model="claude-haiku-5-5")


def _reply(text: str) -> httpx.Response:
    return httpx.Response(
        200, json={"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}
    )


@respx.mock
async def test_grounded_text_is_returned_and_request_is_well_formed() -> None:
    text = (
        "Your sodium reached 2950 mg, above the 2300 mg limit. "
        "Protein came in 40 g under your 150 g target; yogurt or eggs could help."
    )
    route = respx.post(URL).mock(return_value=_reply(text))

    assert await _phraser().phrase(DAY, INSIGHTS) == text

    request = route.calls.last.request
    assert request.headers["x-api-key"] == "sk-test"
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = httpx.Response(200, content=request.content).json()
    assert body["model"] == "claude-haiku-5-5"
    assert body["system"] == SYSTEM_PROMPT
    assert "2950 mg" in body["messages"][0]["content"]


@respx.mock
@pytest.mark.parametrize(
    "text",
    [
        "Sodium hit 2950 mg. Aim for 1500 mg tomorrow.",  # invented number
        "Protein was 41 g short.",  # altered number
        "x" * 801,  # runaway output
    ],
)
async def test_ungrounded_or_oversized_output_is_rejected(text: str) -> None:
    respx.post(URL).mock(return_value=_reply(text))
    assert await _phraser().phrase(DAY, INSIGHTS) is None


@respx.mock
@pytest.mark.parametrize(
    "outcome",
    [
        httpx.Response(529),
        httpx.Response(200, json={"oops": True}),
        httpx.ConnectTimeout("slow"),
        httpx.Response(200, json={"content": []}),
    ],
)
async def test_any_upstream_problem_falls_back_to_none(outcome: object) -> None:
    respx.post(URL).mock(side_effect=[outcome])
    assert await _phraser().phrase(DAY, INSIGHTS) is None


class CountingPhraser:
    def __init__(self, result: str | None) -> None:
        self.calls = 0
        self.result = result

    async def phrase(self, day: CoachDay, insights: tuple[Insight, ...]) -> str | None:
        self.calls += 1
        return self.result


async def test_cache_reuses_successful_phrasings_only() -> None:
    ok, failing = CountingPhraser("Nice day."), CountingPhraser(None)
    cache = InMemoryCache()

    for inner in (ok, failing):
        cached = CachedPhraser(inner, cache, ttl_seconds=60, model=f"m-{id(inner)}")
        await cached.phrase(DAY, INSIGHTS)
        await cached.phrase(DAY, INSIGHTS)

    assert ok.calls == 1
    assert failing.calls == 2  # failures are retried next time, not cached
