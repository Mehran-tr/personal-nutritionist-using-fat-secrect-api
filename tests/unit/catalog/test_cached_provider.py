from nutritionist.core.cache import Cache, InMemoryCache
from nutritionist.modules.catalog.domain.models import Gtin, SearchQuery
from nutritionist.modules.catalog.infrastructure.cached_provider import CachedFoodProvider
from tests.fakes import FakeFoodProvider, make_food


def _cached(inner: FakeFoodProvider, cache: Cache | None = None) -> CachedFoodProvider:
    return CachedFoodProvider(
        inner,
        cache or InMemoryCache(),
        namespace="test",
        food_ttl_seconds=60,
        search_ttl_seconds=60,
    )


async def test_get_is_served_from_cache_and_round_trips_exactly() -> None:
    original = make_food("1", "Apple")
    inner = FakeFoodProvider(foods={"1": original})
    provider = _cached(inner)

    first = await provider.get("1")
    second = await provider.get("1")

    assert first == second == original  # Decimals and tuples survive serialization
    assert inner.calls == ["get:1"]


async def test_search_cache_key_is_case_insensitive_but_page_aware() -> None:
    inner = FakeFoodProvider(foods={"1": make_food("1", "Apple")})
    provider = _cached(inner)

    await provider.search(SearchQuery("Apple"))
    await provider.search(SearchQuery("apple"))
    await provider.search(SearchQuery("apple", page=1))

    assert inner.calls == ["search:Apple:0", "search:apple:1"]


async def test_misses_are_cached_too() -> None:
    inner = FakeFoodProvider()
    provider = _cached(inner)

    assert await provider.find_by_barcode(Gtin("4006381333931")) is None
    assert await provider.find_by_barcode(Gtin("4006381333931")) is None
    assert inner.calls == ["barcode:4006381333931"]


class _BrokenCache(InMemoryCache):
    async def get(self, key: str) -> bytes | None:
        raise ConnectionError("redis down")

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        raise ConnectionError("redis down")


async def test_cache_outage_degrades_to_direct_calls() -> None:
    inner = FakeFoodProvider(foods={"1": make_food("1")})
    provider = _cached(inner, _BrokenCache())

    assert await provider.get("1") is not None
    assert inner.calls == ["get:1"]
