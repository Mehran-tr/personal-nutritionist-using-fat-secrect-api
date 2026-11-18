"""Read-through cache decorator for any ``FoodProvider``."""

import hashlib
from collections.abc import Awaitable, Callable

import structlog
from pydantic import TypeAdapter

from nutritionist.core.cache import Cache
from nutritionist.modules.catalog.domain.models import Food, Gtin, Page, SearchQuery
from nutritionist.modules.catalog.domain.ports import FoodProvider

# Bump when the cached domain shape changes; old entries are then simply ignored.
_SCHEMA_VERSION = "v1"

_food_adapter: TypeAdapter[Food | None] = TypeAdapter(Food | None)
_page_adapter: TypeAdapter[Page[Food]] = TypeAdapter(Page[Food])

logger = structlog.get_logger(__name__)


class CachedFoodProvider:
    def __init__(
        self,
        inner: FoodProvider,
        cache: Cache,
        *,
        namespace: str,
        food_ttl_seconds: int,
        search_ttl_seconds: int,
    ) -> None:
        self._inner = inner
        self._cache = cache
        self._prefix = f"catalog:{_SCHEMA_VERSION}:{namespace}"
        self._food_ttl = food_ttl_seconds
        self._search_ttl = search_ttl_seconds

    async def search(self, query: SearchQuery) -> Page[Food]:
        digest = hashlib.sha256(query.text.lower().encode()).hexdigest()[:24]
        key = f"{self._prefix}:search:{digest}:{query.page}:{query.page_size}"
        return await self._read_through(
            key, _page_adapter, lambda: self._inner.search(query), self._search_ttl
        )

    async def get(self, external_id: str) -> Food | None:
        key = f"{self._prefix}:food:{external_id}"
        return await self._read_through(
            key, _food_adapter, lambda: self._inner.get(external_id), self._food_ttl
        )

    async def find_by_barcode(self, barcode: Gtin) -> Food | None:
        key = f"{self._prefix}:barcode:{barcode.value}"
        return await self._read_through(
            key, _food_adapter, lambda: self._inner.find_by_barcode(barcode), self._food_ttl
        )

    async def _read_through[T](
        self,
        key: str,
        adapter: TypeAdapter[T],
        load: Callable[[], Awaitable[T]],
        ttl: int,
    ) -> T:
        cached = await self._safe_get(key)
        if cached is not None:
            return adapter.validate_json(cached)

        value = await load()
        await self._safe_set(key, adapter.dump_json(value), ttl)
        return value

    # A cache outage must degrade performance, never availability.
    async def _safe_get(self, key: str) -> bytes | None:
        try:
            return await self._cache.get(key)
        except Exception:
            logger.warning("cache_get_failed", key=key, exc_info=True)
            return None

    async def _safe_set(self, key: str, value: bytes, ttl: int) -> None:
        try:
            await self._cache.set(key, value, ttl)
        except Exception:
            logger.warning("cache_set_failed", key=key, exc_info=True)
