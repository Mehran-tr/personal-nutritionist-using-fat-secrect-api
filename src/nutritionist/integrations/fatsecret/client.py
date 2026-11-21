"""Thin, typed client for the fatsecret Platform REST API (URL-based endpoints).

Responsibilities: auth headers, common params, retries, error envelopes and
response-shape validation. It knows nothing about our domain.
"""

import time
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, ValidationError
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from nutritionist.core.config import FatSecretSettings
from nutritionist.core.metrics import UPSTREAM_LATENCY
from nutritionist.integrations.fatsecret.auth import TokenProvider
from nutritionist.integrations.fatsecret.errors import (
    INVALID_TOKEN,
    FatSecretApiError,
    FatSecretProtocolError,
    FatSecretUnavailableError,
)
from nutritionist.integrations.fatsecret.schemas import (
    FsBarcodeResponse,
    FsErrorResponse,
    FsFood,
    FsFoodGetResponse,
    FsFoodsSearch,
    FsFoodsSearchResponse,
)

logger = structlog.get_logger(__name__)

_NO_MATCH_FOOD_ID = "0"


class _RetryableError(Exception):
    """Internal signal: this attempt failed in a way that is worth retrying."""


class FatSecretClient:
    def __init__(
        self,
        http: httpx.AsyncClient,
        tokens: TokenProvider,
        settings: FatSecretSettings,
    ) -> None:
        self._http = http
        self._tokens = tokens
        self._settings = settings
        self._base_url = settings.base_url.rstrip("/")

    # ------------------------------------------------------------------ endpoints

    async def search_foods(
        self, expression: str, *, page_number: int = 0, max_results: int = 20
    ) -> FsFoodsSearch:
        payload = await self._get(
            self._settings.search_path,
            {
                "search_expression": expression,
                "page_number": page_number,
                "max_results": max_results,
                "flag_default_serving": "true",
            },
        )
        return self._parse(FsFoodsSearchResponse, payload).foods_search

    async def get_food(self, food_id: str) -> FsFood:
        payload = await self._get(
            self._settings.food_get_path,
            {"food_id": food_id, "flag_default_serving": "true"},
        )
        return self._parse(FsFoodGetResponse, payload).food

    async def find_food_id_for_barcode(self, gtin13: str) -> str | None:
        """Return the fatsecret food id for a GTIN-13 barcode, or ``None`` if unknown."""
        payload = await self._get(self._settings.barcode_path, {"barcode": gtin13})
        food_id = self._parse(FsBarcodeResponse, payload).food_id
        return None if food_id in ("", _NO_MATCH_FOOD_ID) else food_id

    # ------------------------------------------------------------------ transport

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {"format": "json", **self._locale_params(), **params}
        url = f"{self._base_url}/{path.lstrip('/')}"

        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._settings.max_attempts),
            # Exponential backoff with full jitter, so instances don't retry in lockstep.
            wait=wait_random_exponential(
                multiplier=self._settings.retry_backoff_seconds,
                max=self._settings.retry_backoff_seconds * 10,
            ),
            retry=retry_if_exception_type(_RetryableError),
        )
        try:
            async for attempt in retrying:
                with attempt:
                    return await self._attempt(url, query)
        except RetryError as exc:
            logger.warning("fatsecret_unavailable", path=path, attempts=self._settings.max_attempts)
            raise FatSecretUnavailableError(f"fatsecret unavailable for '{path}'.") from exc
        raise AssertionError("unreachable")  # pragma: no cover

    async def _attempt(self, url: str, query: dict[str, Any]) -> dict[str, Any]:
        token = await self._tokens.get_token()
        started = time.perf_counter()
        try:
            response = await self._http.get(
                url, params=query, headers={"Authorization": f"Bearer {token}"}
            )
        except httpx.TimeoutException as exc:
            UPSTREAM_LATENCY.labels("fatsecret", "timeout").observe(time.perf_counter() - started)
            raise _RetryableError("timeout") from exc
        except httpx.TransportError as exc:
            UPSTREAM_LATENCY.labels("fatsecret", "error").observe(time.perf_counter() - started)
            raise _RetryableError("transport") from exc
        UPSTREAM_LATENCY.labels("fatsecret", str(response.status_code)).observe(
            time.perf_counter() - started
        )

        if response.status_code == 429 or response.status_code >= 500:
            raise _RetryableError(f"http {response.status_code}")
        if response.status_code == 401:
            self._tokens.invalidate()
            raise _RetryableError("unauthorized")

        payload = self._decode(response)

        # fatsecret often reports errors with HTTP 200 and an error envelope.
        if "error" in payload:
            error = self._parse(FsErrorResponse, payload).error
            if error.code == INVALID_TOKEN:  # expired/revoked token: refresh and retry
                self._tokens.invalidate()
                raise _RetryableError("invalid token")
            raise FatSecretApiError(error.code, error.message)
        if response.status_code >= 400:
            raise FatSecretApiError(response.status_code, "Unexpected HTTP error.")
        return payload

    def _locale_params(self) -> dict[str, str]:
        params: dict[str, str] = {}
        if self._settings.region:
            params["region"] = self._settings.region
            if self._settings.language:  # ignored by fatsecret without region
                params["language"] = self._settings.language
        return params

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise FatSecretProtocolError("Response is not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise FatSecretProtocolError("Expected a JSON object.")
        return payload

    @staticmethod
    def _parse[M: BaseModel](model: type[M], payload: dict[str, Any]) -> M:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise FatSecretProtocolError(
                f"Unexpected fatsecret response shape for {model.__name__}."
            ) from exc
