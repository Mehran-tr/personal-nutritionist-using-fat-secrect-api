"""Composition root: the only place that knows which adapter implements which port."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from nutritionist.core.cache import Cache, InMemoryCache, RedisCache
from nutritionist.core.config import Settings
from nutritionist.integrations.fatsecret.auth import ClientCredentialsTokenProvider
from nutritionist.integrations.fatsecret.client import FatSecretClient
from nutritionist.modules.catalog.domain.ports import FoodProvider
from nutritionist.modules.catalog.infrastructure.cached_provider import CachedFoodProvider
from nutritionist.modules.catalog.infrastructure.fatsecret_provider import FatSecretFoodProvider


@dataclass(slots=True)
class Container:
    settings: Settings
    http: httpx.AsyncClient
    cache: Cache
    food_provider: FoodProvider

    async def aclose(self) -> None:
        await self.http.aclose()
        await self.cache.aclose()


ContainerFactory = Callable[[Settings], Awaitable[Container]]


def build_cache(settings: Settings) -> Cache:
    if settings.cache.backend == "memory":
        return InMemoryCache()
    return RedisCache.from_url(settings.cache.redis_url)


async def build_container(settings: Settings) -> Container:
    fs = settings.fatsecret
    http = httpx.AsyncClient(
        timeout=httpx.Timeout(fs.timeout_seconds),
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        headers={"User-Agent": f"{settings.app_name}/0.1"},
    )
    cache = build_cache(settings)

    tokens = ClientCredentialsTokenProvider(
        http,
        token_url=fs.token_url,
        client_id=fs.client_id.get_secret_value(),
        client_secret=fs.client_secret.get_secret_value(),
        scopes=fs.scopes,
        refresh_margin_seconds=fs.token_refresh_margin_seconds,
    )
    fatsecret = FatSecretFoodProvider(FatSecretClient(http, tokens, fs))

    food_provider = CachedFoodProvider(
        fatsecret,
        cache,
        namespace=f"fatsecret:{fs.region or 'default'}",
        food_ttl_seconds=settings.cache.food_ttl_seconds,
        search_ttl_seconds=settings.cache.search_ttl_seconds,
    )
    return Container(settings=settings, http=http, cache=cache, food_provider=food_provider)
