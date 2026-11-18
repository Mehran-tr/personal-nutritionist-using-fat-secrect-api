import pytest

from nutritionist.modules.catalog.application.use_cases import GetFood, LookupBarcode, SearchFoods
from nutritionist.modules.catalog.domain.errors import FoodNotFoundError, InvalidBarcodeError
from tests.fakes import FakeFoodProvider, make_food


@pytest.fixture
def provider() -> FakeFoodProvider:
    apple = make_food("1", "Apple")
    return FakeFoodProvider(
        foods={"1": apple, "2": make_food("2", "Apple pie", kcal="237")},
        barcodes={"4006381333931": "1"},
    )


async def test_search_returns_matching_page(provider: FakeFoodProvider) -> None:
    page = await SearchFoods(provider).execute("  apple ", page_size=1)

    assert page.total == 2
    assert [f.name for f in page.items] == ["Apple"]
    assert page.has_next
    assert provider.calls == ["search:apple:0"]


async def test_get_food_raises_when_unknown(provider: FakeFoodProvider) -> None:
    with pytest.raises(FoodNotFoundError):
        await GetFood(provider).execute("404")


async def test_barcode_lookup_normalises_before_calling_provider(
    provider: FakeFoodProvider,
) -> None:
    food = await LookupBarcode(provider).execute("4006381333931")
    assert food.name == "Apple"


async def test_invalid_barcode_never_reaches_provider(provider: FakeFoodProvider) -> None:
    with pytest.raises(InvalidBarcodeError):
        await LookupBarcode(provider).execute("4006381333932")
    assert provider.calls == []


async def test_unknown_barcode_raises_not_found(provider: FakeFoodProvider) -> None:
    with pytest.raises(FoodNotFoundError):
        await LookupBarcode(provider).execute("036000291452")
