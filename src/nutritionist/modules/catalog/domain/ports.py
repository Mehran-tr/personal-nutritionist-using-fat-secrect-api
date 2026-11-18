from typing import Protocol

from nutritionist.modules.catalog.domain.models import Food, Gtin, Page, SearchQuery


class FoodProvider(Protocol):
    """Source of food and nutrition data (fatsecret today, others tomorrow).

    Implementations must raise only catalog domain errors, never transport or
    vendor-specific exceptions.
    """

    async def search(self, query: SearchQuery) -> Page[Food]: ...

    async def get(self, external_id: str) -> Food | None:
        """Return the food, or ``None`` if the provider does not know the id."""
        ...

    async def find_by_barcode(self, barcode: Gtin) -> Food | None: ...
