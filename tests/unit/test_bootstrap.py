from nutritionist.bootstrap import build_container
from nutritionist.core.cache import InMemoryCache
from nutritionist.core.config import Settings
from nutritionist.modules.catalog.infrastructure.cached_provider import CachedFoodProvider


async def test_container_wires_cached_fatsecret_provider(settings: Settings) -> None:
    container = await build_container(settings)
    try:
        assert isinstance(container.cache, InMemoryCache)
        assert isinstance(container.food_provider, CachedFoodProvider)
    finally:
        await container.aclose()
