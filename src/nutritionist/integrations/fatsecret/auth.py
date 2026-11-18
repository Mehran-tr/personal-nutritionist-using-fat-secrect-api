"""OAuth 2.0 client-credentials token management for fatsecret.

One token is shared by every request in the process. It is refreshed shortly
before it expires, and concurrent callers never trigger more than one refresh.
"""

import asyncio
import time
from collections.abc import Callable
from typing import Protocol

import httpx
import structlog
from pydantic import BaseModel, ValidationError

from nutritionist.integrations.fatsecret.errors import (
    FatSecretAuthError,
    FatSecretUnavailableError,
)

logger = structlog.get_logger(__name__)


class TokenProvider(Protocol):
    async def get_token(self) -> str: ...

    def invalidate(self) -> None: ...


class _TokenResponse(BaseModel):
    access_token: str
    expires_in: int
    token_type: str = "Bearer"


class ClientCredentialsTokenProvider:
    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        token_url: str,
        client_id: str,
        client_secret: str,
        scopes: str,
        refresh_margin_seconds: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._http = http
        self._token_url = token_url
        self._credentials = (client_id, client_secret)
        self._scopes = scopes
        self._margin = refresh_margin_seconds
        self._clock = clock

        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        if (token := self._valid_token()) is not None:
            return token
        async with self._lock:
            # Another coroutine may have refreshed while we waited for the lock.
            if (token := self._valid_token()) is not None:
                return token
            return await self._refresh()

    def invalidate(self) -> None:
        self._token = None
        self._expires_at = 0.0

    def _valid_token(self) -> str | None:
        if self._token and self._clock() < self._expires_at - self._margin:
            return self._token
        return None

    async def _refresh(self) -> str:
        try:
            response = await self._http.post(
                self._token_url,
                data={"grant_type": "client_credentials", "scope": self._scopes},
                auth=self._credentials,
            )
        except httpx.HTTPError as exc:
            raise FatSecretUnavailableError("Token endpoint unreachable.") from exc

        if response.status_code >= 500:
            raise FatSecretUnavailableError(f"Token endpoint returned {response.status_code}.")
        if response.status_code >= 400:
            # Never log the response body: it can echo credentials back.
            raise FatSecretAuthError(f"Token request rejected ({response.status_code}).")

        try:
            payload = _TokenResponse.model_validate_json(response.content)
        except ValidationError as exc:
            raise FatSecretAuthError("Malformed token response.") from exc

        self._token = payload.access_token
        self._expires_at = self._clock() + payload.expires_in
        logger.info("fatsecret_token_refreshed", expires_in=payload.expires_in)
        return self._token
