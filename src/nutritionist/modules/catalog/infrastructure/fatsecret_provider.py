"""``FoodProvider`` implementation backed by fatsecret."""

from collections.abc import Iterator
from contextlib import contextmanager

from nutritionist.integrations.fatsecret.client import FatSecretClient
from nutritionist.integrations.fatsecret.errors import (
    FatSecretApiError,
    FatSecretError,
    FatSecretUnavailableError,
)
from nutritionist.modules.catalog.domain.errors import (
    FoodProviderError,
    FoodProviderUnavailableError,
)
from nutritionist.modules.catalog.domain.models import Food, Gtin, Page, SearchQuery
from nutritionist.modules.catalog.infrastructure import fatsecret_mapper as mapper


class FatSecretFoodProvider:
    def __init__(self, client: FatSecretClient) -> None:
        self._client = client

    async def search(self, query: SearchQuery) -> Page[Food]:
        with _translate_errors():
            result = await self._client.search_foods(
                query.text, page_number=query.page, max_results=query.page_size
            )
        return mapper.to_page(result, query)

    async def get(self, external_id: str) -> Food | None:
        with _translate_errors():
            try:
                fs_food = await self._client.get_food(external_id)
            except FatSecretApiError as exc:
                if exc.is_invalid_id:
                    return None
                raise
        return mapper.to_food(fs_food)

    async def find_by_barcode(self, barcode: Gtin) -> Food | None:
        with _translate_errors():
            food_id = await self._client.find_food_id_for_barcode(barcode.value)
        if food_id is None:
            return None
        return await self.get(food_id)


@contextmanager
def _translate_errors() -> Iterator[None]:
    """Vendor exceptions must not leak past the adapter boundary."""
    try:
        yield
    except FatSecretUnavailableError as exc:
        raise FoodProviderUnavailableError(
            "The food database is temporarily unavailable. Please retry shortly."
        ) from exc
    except FatSecretError as exc:
        raise FoodProviderError("The food database returned an unexpected error.") from exc
