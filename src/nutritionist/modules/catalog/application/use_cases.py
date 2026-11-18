"""Catalog use cases: one class per user-facing action.

They are thin today. They are still the single place to add cross-cutting
behaviour later (search history, per-user regional settings, metrics), so
routers never talk to the provider directly.
"""

from dataclasses import dataclass

from nutritionist.modules.catalog.domain.errors import FoodNotFoundError
from nutritionist.modules.catalog.domain.models import Food, Gtin, Page, SearchQuery
from nutritionist.modules.catalog.domain.ports import FoodProvider


@dataclass(frozen=True, slots=True)
class SearchFoods:
    provider: FoodProvider

    async def execute(self, text: str, page: int = 0, page_size: int = 20) -> Page[Food]:
        query = SearchQuery(text=text, page=page, page_size=page_size)
        return await self.provider.search(query)


@dataclass(frozen=True, slots=True)
class GetFood:
    provider: FoodProvider

    async def execute(self, external_id: str) -> Food:
        food = await self.provider.get(external_id)
        if food is None:
            raise FoodNotFoundError(f"No food with id '{external_id}'.")
        return food


@dataclass(frozen=True, slots=True)
class LookupBarcode:
    provider: FoodProvider

    async def execute(self, raw_barcode: str) -> Food:
        barcode = Gtin(raw_barcode)
        food = await self.provider.find_by_barcode(barcode)
        if food is None:
            raise FoodNotFoundError(f"No food registered for barcode '{barcode.value}'.")
        return food
