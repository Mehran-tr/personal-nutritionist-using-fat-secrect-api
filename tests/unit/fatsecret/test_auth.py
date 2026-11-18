import asyncio

import httpx
import pytest
import respx

from nutritionist.integrations.fatsecret.auth import ClientCredentialsTokenProvider
from nutritionist.integrations.fatsecret.errors import (
    FatSecretAuthError,
    FatSecretUnavailableError,
)

TOKEN_URL = "https://oauth.test/connect/token"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def tokens(clock: FakeClock) -> ClientCredentialsTokenProvider:
    return ClientCredentialsTokenProvider(
        httpx.AsyncClient(),
        token_url=TOKEN_URL,
        client_id="id",
        client_secret="secret",
        scopes="premier",
        refresh_margin_seconds=60,
        clock=clock,
    )


def _token(value: str, expires_in: int = 86_400) -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": value, "expires_in": expires_in, "token_type": "Bearer"}
    )


@respx.mock
async def test_fetches_with_client_credentials_and_caches(
    tokens: ClientCredentialsTokenProvider,
) -> None:
    route = respx.post(TOKEN_URL).mock(return_value=_token("t1"))

    assert await tokens.get_token() == "t1"
    assert await tokens.get_token() == "t1"

    assert route.call_count == 1
    request = route.calls.last.request
    assert request.headers["authorization"].startswith("Basic ")
    assert b"grant_type=client_credentials" in request.content
    assert b"scope=premier" in request.content


@respx.mock
async def test_refreshes_before_expiry(
    tokens: ClientCredentialsTokenProvider, clock: FakeClock
) -> None:
    respx.post(TOKEN_URL).mock(side_effect=[_token("t1", 3_600), _token("t2", 3_600)])

    assert await tokens.get_token() == "t1"
    clock.now += 3_600 - 59  # inside the refresh margin
    assert await tokens.get_token() == "t2"


@respx.mock
async def test_concurrent_callers_share_one_refresh(
    tokens: ClientCredentialsTokenProvider,
) -> None:
    route = respx.post(TOKEN_URL).mock(return_value=_token("t1"))

    results = await asyncio.gather(*(tokens.get_token() for _ in range(10)))

    assert set(results) == {"t1"}
    assert route.call_count == 1


@respx.mock
async def test_invalidate_forces_refresh(tokens: ClientCredentialsTokenProvider) -> None:
    respx.post(TOKEN_URL).mock(side_effect=[_token("t1"), _token("t2")])

    await tokens.get_token()
    tokens.invalidate()
    assert await tokens.get_token() == "t2"


@respx.mock
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(401, json={"error": "invalid_client"}), FatSecretAuthError),
        (httpx.Response(200, json={"unexpected": True}), FatSecretAuthError),
        (httpx.Response(503), FatSecretUnavailableError),
    ],
)
async def test_failures_are_typed(
    tokens: ClientCredentialsTokenProvider,
    response: httpx.Response,
    error: type[Exception],
) -> None:
    respx.post(TOKEN_URL).mock(return_value=response)
    with pytest.raises(error):
        await tokens.get_token()


@respx.mock
async def test_network_error_is_unavailable(tokens: ClientCredentialsTokenProvider) -> None:
    respx.post(TOKEN_URL).mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(FatSecretUnavailableError):
        await tokens.get_token()
