"""LLM phrasing for coach insights: guarded, cached and optional.

The rules decide *what* to say. The model only decides *how* to say it. Three
guards back that up:
1. The prompt contains only the insights (no profile, no free text from the user).
2. Output is rejected if it mentions any number that isn't in the insights
   (a cheap but effective check against invented figures).
3. Any failure returns ``None``, and the API still answers with the rule-based insights.
"""

import hashlib
import json
import re
from decimal import Decimal
from typing import Protocol

import structlog

from nutritionist.core.background import BackgroundRunner
from nutritionist.core.cache import Cache
from nutritionist.core.metrics import CACHE_REQUESTS
from nutritionist.integrations.anthropic.client import AnthropicClient, AnthropicError
from nutritionist.modules.coach.application.use_cases import PhraseResult
from nutritionist.modules.coach.domain.models import CoachDay, Insight

logger = structlog.get_logger(__name__)

PROMPT_VERSION = "v1"  # bump to invalidate cached phrasings after prompt changes
MAX_SUMMARY_CHARS = 800

SYSTEM_PROMPT = """\
You are the friendly voice of a nutrition-tracking app.
You receive a list of insights that were already computed by the app's rules.
Rewrite them as ONE short paragraph (2-4 sentences) addressed to the user as "you".

Rules you must follow:
- Use only the facts in the insights. Do not add numbers, foods, diagnoses or claims.
- Every number you mention must appear exactly as given in the insights.
- Mention warnings first. Keep safety advice (e.g. "talk to a doctor") if present.
- No medical advice, no weight or body judgments, no praise for eating little.
- Plain text only: no lists, no markdown, no emojis.\
"""

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


class LlmPhraser:
    def __init__(self, client: AnthropicClient, *, model: str, max_tokens: int = 300) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens

    async def phrase(self, day: CoachDay, insights: tuple[Insight, ...]) -> str | None:
        payload = json.dumps(
            {
                "day_status": day.status.value,
                "insights": [{"severity": i.severity.name, "text": i.message} for i in insights],
            }
        )
        try:
            text = await self._client.complete(
                model=self._model,
                system=SYSTEM_PROMPT,
                user=payload,
                max_tokens=self._max_tokens,
            )
        except AnthropicError:
            logger.warning("coach_phrasing_failed", exc_info=True)
            return None

        if len(text) > MAX_SUMMARY_CHARS or not _numbers_are_grounded(text, insights):
            logger.warning("coach_phrasing_rejected", length=len(text))
            return None
        return text


def _numbers_are_grounded(text: str, insights: tuple[Insight, ...]) -> bool:
    allowed = {_normalise(m) for i in insights for m in _NUMBER.findall(i.message)}
    return all(_normalise(m) in allowed for m in _NUMBER.findall(text))


def _normalise(number: str) -> str:
    value = Decimal(number.replace(",", "."))
    return str(value.normalize()) if value % 1 else str(int(value))


class TextGenerator(Protocol):
    async def phrase(self, day: CoachDay, insights: tuple[Insight, ...]) -> str | None: ...


class CachedPhraser:
    """Same insights, same text: completed days are reviewed again and again, and
    each phrasing costs an API call (~1-3 s). Failures are not cached.

    With a ``runner``, a cache miss never makes the user wait. Generation starts
    in the background (deduplicated per key) and the response says
    ``pending``. The next request is a cache hit. Without one, it runs inline.
    """

    def __init__(
        self,
        inner: TextGenerator,
        cache: Cache,
        *,
        ttl_seconds: int,
        model: str,
        runner: BackgroundRunner | None = None,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._ttl = ttl_seconds
        self._model = model
        self._runner = runner

    async def phrase(self, day: CoachDay, insights: tuple[Insight, ...]) -> PhraseResult:
        fingerprint = json.dumps(
            [PROMPT_VERSION, self._model, day.status.value, [i.message for i in insights]]
        )
        key = f"coach:phrase:{hashlib.sha256(fingerprint.encode()).hexdigest()}"
        try:
            cached = await self._cache.get(key)
        except Exception:
            cached = None
        if cached is not None:
            CACHE_REQUESTS.labels("coach_phrase", "hit").inc()
            return PhraseResult(cached.decode())
        CACHE_REQUESTS.labels("coach_phrase", "miss").inc()

        if self._runner is not None:
            self._runner.spawn(key, "coach_phrase", lambda: self._fill(key, day, insights))
            return PhraseResult(pending=True)
        return PhraseResult(await self._fill(key, day, insights))

    async def _fill(self, key: str, day: CoachDay, insights: tuple[Insight, ...]) -> str | None:
        text = await self._inner.phrase(day, insights)
        if text is not None:
            try:
                await self._cache.set(key, text.encode(), self._ttl)
            except Exception:
                logger.warning("coach_cache_set_failed", exc_info=True)
        return text
