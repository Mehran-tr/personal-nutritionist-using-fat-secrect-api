import httpx
import pytest
import respx

from nutritionist.core.config import FatSecretSettings
from nutritionist.integrations.fatsecret.client import FatSecretClient
from nutritionist.integrations.fatsecret.errors import (
    FatSecretApiError,
    FatSecretProtocolError,
    FatSecretUnavailableError,
)
from tests.conftest import load_fixture

BASE = "https://platform.test/rest"


class StubTokens:
    def __init__(self) -> None:
        self.issued = 0
        self.invalidations = 0

    async def get_token(self) -> str:
        self.issued += 1
        return f"token-{self.issued}"

    def invalidate(self) -> None:
        self.invalidations += 1


@pytest.fixture
def tokens() -> StubTokens:
    return StubTokens()


@pytest.fixture
def client(fatsecret_settings: FatSecretSettings, tokens: StubTokens) -> FatSecretClient:
    return FatSecretClient(httpx.AsyncClient(), tokens, fatsecret_settings)


@respx.mock
async def test_search_sends_auth_and_common_params(client: FatSecretClient) -> None:
    route = respx.get(f"{BASE}/foods/search/v6").mock(
        return_value=httpx.Response(200, json=load_fixture("foods_search_v6.json"))
    )

    result = await client.search_foods("chicken", page_number=2, max_results=10)

    assert result.total_results == 137
    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer token-1"
    params = request.url.params
    assert params["format"] == "json"
    assert params["search_expression"] == "chicken"
    assert params["page_number"] == "2"
    assert params["max_results"] == "10"


@respx.mock
async def test_region_and_language_are_sent_only_together(
    fatsecret_settings: FatSecretSettings, tokens: StubTokens
) -> None:
    settings = fatsecret_settings.model_copy(update={"region": "DE", "language": "de"})
    client = FatSecretClient(httpx.AsyncClient(), tokens, settings)
    route = respx.get(f"{BASE}/food/v6").mock(
        return_value=httpx.Response(200, json=load_fixture("food_get_v6.json"))
    )

    await client.get_food("1641")

    params = route.calls.last.request.url.params
    assert (params["region"], params["language"]) == ("DE", "de")


@respx.mock
@pytest.mark.parametrize(
    "failure",
    [httpx.Response(503), httpx.Response(429), httpx.ConnectTimeout("slow")],
)
async def test_retries_transient_failures(
    client: FatSecretClient, failure: httpx.Response | Exception
) -> None:
    route = respx.get(f"{BASE}/food/v6").mock(
        side_effect=[failure, httpx.Response(200, json=load_fixture("food_get_v6.json"))]
    )

    food = await client.get_food("1641")

    assert food.food_id == "1641"
    assert route.call_count == 2


@respx.mock
async def test_gives_up_after_max_attempts(client: FatSecretClient) -> None:
    route = respx.get(f"{BASE}/food/v6").mock(return_value=httpx.Response(502))

    with pytest.raises(FatSecretUnavailableError):
        await client.get_food("1641")
    assert route.call_count == 3


@respx.mock
async def test_invalid_token_envelope_triggers_refresh_and_retry(
    client: FatSecretClient, tokens: StubTokens
) -> None:
    route = respx.get(f"{BASE}/food/v6").mock(
        side_effect=[
            httpx.Response(200, json=load_fixture("error_invalid_token.json")),
            httpx.Response(200, json=load_fixture("food_get_v6.json")),
        ]
    )

    await client.get_food("1641")

    assert tokens.invalidations == 1
    assert route.calls.last.request.headers["authorization"] == "Bearer token-2"


@respx.mock
async def test_http_401_triggers_refresh_and_retry(
    client: FatSecretClient, tokens: StubTokens
) -> None:
    respx.get(f"{BASE}/food/v6").mock(
        side_effect=[
            httpx.Response(401),
            httpx.Response(200, json=load_fixture("food_get_v6.json")),
        ]
    )
    await client.get_food("1641")
    assert tokens.invalidations == 1


@respx.mock
async def test_business_errors_are_not_retried(client: FatSecretClient) -> None:
    route = respx.get(f"{BASE}/food/v6").mock(
        return_value=httpx.Response(200, json=load_fixture("error_invalid_id.json"))
    )

    with pytest.raises(FatSecretApiError) as exc_info:
        await client.get_food("999")

    assert exc_info.value.is_invalid_id
    assert route.call_count == 1


@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>maintenance</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(200, json={"food": {"food_name": "missing id"}}),
    ],
)
async def test_unexpected_payloads_raise_protocol_error(
    client: FatSecretClient, response: httpx.Response
) -> None:
    respx.get(f"{BASE}/food/v6").mock(return_value=response)
    with pytest.raises(FatSecretProtocolError):
        await client.get_food("1641")


@respx.mock
@pytest.mark.parametrize(
    ("fixture", "expected"),
    [("barcode_found.json", "50953"), ("barcode_not_found.json", None)],
)
async def test_barcode_lookup(client: FatSecretClient, fixture: str, expected: str | None) -> None:
    route = respx.get(f"{BASE}/food/barcode/find-by-id/v1").mock(
        return_value=httpx.Response(200, json=load_fixture(fixture))
    )

    assert await client.find_food_id_for_barcode("0041570054161") == expected
    assert route.calls.last.request.url.params["barcode"] == "0041570054161"
