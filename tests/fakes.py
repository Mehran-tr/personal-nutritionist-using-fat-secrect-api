"""In-memory test doubles and factories. Prefer these over mocks."""

from dataclasses import dataclass, field
from decimal import Decimal

from nutritionist.modules.catalog.domain.models import (
    Food,
    FoodRef,
    FoodType,
    Gtin,
    Nutrients,
    Page,
    SearchQuery,
    Serving,
)


def make_food(external_id: str = "1", name: str = "Apple", *, kcal: str = "52") -> Food:
    return Food(
        ref=FoodRef(provider="fake", external_id=external_id),
        name=name,
        type=FoodType.GENERIC,
        servings=(
            Serving(
                id=f"{external_id}-100g",
                description="100 g",
                metric_amount=Decimal("100"),
                metric_unit="g",
                is_default=True,
                nutrients=Nutrients(
                    calories_kcal=Decimal(kcal),
                    protein_g=Decimal("0.3"),
                    carbohydrate_g=Decimal("13.8"),
                    fat_g=Decimal("0.2"),
                    fiber_g=Decimal("2.4"),
                ),
            ),
        ),
    )


@dataclass
class FakeFoodProvider:
    foods: dict[str, Food] = field(default_factory=dict)
    barcodes: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    error: Exception | None = None

    async def search(self, query: SearchQuery) -> Page[Food]:
        self._record(f"search:{query.text}:{query.page}")
        matches = [f for f in self.foods.values() if query.text.lower() in f.name.lower()]
        start = query.page * query.page_size
        return Page(
            items=tuple(matches[start : start + query.page_size]),
            page=query.page,
            page_size=query.page_size,
            total=len(matches),
        )

    async def get(self, external_id: str) -> Food | None:
        self._record(f"get:{external_id}")
        return self.foods.get(external_id)

    async def find_by_barcode(self, barcode: Gtin) -> Food | None:
        self._record(f"barcode:{barcode.value}")
        food_id = self.barcodes.get(barcode.value)
        return self.foods.get(food_id) if food_id else None

    def _record(self, call: str) -> None:
        self.calls.append(call)
        if self.error is not None:
            raise self.error
