"""Minimal Anthropic Messages API client (text in, text out).

Deliberately tiny: one call, typed errors, no retries. Callers that use it for
optional features fall back instead of retrying and making the user wait.
"""

import time
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from nutritionist.core.metrics import UPSTREAM_LATENCY

API_VERSION = "2023-06-01"


class AnthropicError(Exception):
    """Any failure: transport, HTTP status, or unexpected response shape."""


class _TextBlock(BaseModel):
    type: str
    text: str | None = None


class _MessageResponse(BaseModel):
    content: list[_TextBlock]
    stop_reason: str | None = None


class AnthropicClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        timeout_seconds: float = 8.0,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self._url = f"{base_url.rstrip('/')}/v1/messages"
        self._timeout = timeout_seconds

    async def complete(
        self, *, model: str, system: str, user: str, max_tokens: int, temperature: float = 0.3
    ) -> str:
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        started = time.perf_counter()
        try:
            response = await self._http.post(
                self._url, json=body, headers=headers, timeout=self._timeout
            )
        except httpx.HTTPError as exc:
            UPSTREAM_LATENCY.labels("anthropic", "error").observe(time.perf_counter() - started)
            raise AnthropicError("Anthropic API unreachable.") from exc
        UPSTREAM_LATENCY.labels("anthropic", str(response.status_code)).observe(
            time.perf_counter() - started
        )
        if response.status_code != 200:
            raise AnthropicError(f"Anthropic API returned {response.status_code}.")

        try:
            message = _MessageResponse.model_validate_json(response.content)
        except ValidationError as exc:
            raise AnthropicError("Unexpected Anthropic response shape.") from exc
        text = "".join(b.text or "" for b in message.content if b.type == "text").strip()
        if not text:
            raise AnthropicError("Empty completion.")
        return text
