import httpx
import pytest
import respx

from nutritionist.core.config import FatSecretSettings
from nutritionist.integrations.fatsecret.client import FatSecretClient
from nutritionist.modules.catalog.domain.errors import (
    FoodProviderError,
    FoodProviderUnavailableError,
)
from nutritionist.modules.catalog.domain.models import Gtin, SearchQuery
from nutritionist.modules.catalog.infrastructure.fatsecret_provider import FatSecretFoodProvider
from tests.conftest import load_fixture

BASE = "https://platform.test/rest"


class StaticTokens:
    async def get_token(self) -> str:
        return "token"

    def invalidate(self) -> None:
        pass


@pytest.fixture
def provider(fatsecret_settings: FatSecretSettings) -> FatSecretFoodProvider:
    return FatSecretFoodProvider(
        FatSecretClient(httpx.AsyncClient(), StaticTokens(), fatsecret_settings)
    )


@respx.mock
async def test_search_returns_domain_page(provider: FatSecretFoodProvider) -> None:
    respx.get(f"{BASE}/foods/search/v6").mock(
        return_value=httpx.Response(200, json=load_fixture("foods_search_v6.json"))
    )
    page = await provider.search(SearchQuery("chicken"))
    assert [f.name for f in page.items] == ["Chicken Breast", "Whole Grain Cheerios"]


@respx.mock
async def test_unknown_id_is_none_not_an_error(provider: FatSecretFoodProvider) -> None:
    respx.get(f"{BASE}/food/v6").mock(
        return_value=httpx.Response(200, json=load_fixture("error_invalid_id.json"))
    )
    assert await provider.get("999") is None


@respx.mock
async def test_barcode_resolves_id_then_fetches_food(provider: FatSecretFoodProvider) -> None:
    respx.get(f"{BASE}/food/barcode/find-by-id/v1").mock(
        return_value=httpx.Response(200, json=load_fixture("barcode_found.json"))
    )
    food_route = respx.get(f"{BASE}/food/v6").mock(
        return_value=httpx.Response(200, json=load_fixture("food_get_v6.json"))
    )

    food = await provider.find_by_barcode(Gtin("4006381333931"))

    assert food is not None
    assert food_route.calls.last.request.url.params["food_id"] == "50953"


@respx.mock
async def test_unknown_barcode_skips_food_lookup(provider: FatSecretFoodProvider) -> None:
    respx.get(f"{BASE}/food/barcode/find-by-id/v1").mock(
        return_value=httpx.Response(200, json=load_fixture("barcode_not_found.json"))
    )
    assert await provider.find_by_barcode(Gtin("4006381333931")) is None


@respx.mock
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(503), FoodProviderUnavailableError),
        (httpx.Response(200, json={"error": {"code": 14, "message": "scope"}}), FoodProviderError),
        (httpx.Response(200, text="garbage"), FoodProviderError),
    ],
)
async def test_vendor_errors_become_domain_errors(
    provider: FatSecretFoodProvider, response: httpx.Response, error: type[Exception]
) -> None:
    respx.get(f"{BASE}/food/v6").mock(return_value=response)
    with pytest.raises(error):
        await provider.get("1641")
