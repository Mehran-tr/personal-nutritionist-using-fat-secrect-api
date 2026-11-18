"""Public API contract for the catalog. Decoupled from domain models on purpose:
the domain can evolve without breaking clients, and vice versa."""

from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, PlainSerializer

from nutritionist.modules.catalog.domain.models import Food, FoodType, Page, Serving

# Decimal internally, a plain JSON number on the wire.
Num = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class NutrientsOut(BaseModel):
    calories_kcal: Num
    protein_g: Num
    carbohydrate_g: Num
    fat_g: Num
    saturated_fat_g: Num | None
    trans_fat_g: Num | None
    fiber_g: Num | None
    sugar_g: Num | None
    added_sugars_g: Num | None
    sodium_mg: Num | None
    potassium_mg: Num | None
    cholesterol_mg: Num | None


class ServingOut(BaseModel):
    id: str
    description: str
    metric_amount: Num | None
    metric_unit: str | None
    number_of_units: Num | None
    is_default: bool
    nutrients: NutrientsOut

    @classmethod
    def from_domain(cls, serving: Serving) -> "ServingOut":
        n = serving.nutrients
        return cls(
            id=serving.id,
            description=serving.description,
            metric_amount=serving.metric_amount,
            metric_unit=serving.metric_unit,
            number_of_units=serving.number_of_units,
            is_default=serving.is_default,
            nutrients=NutrientsOut(
                calories_kcal=n.calories_kcal,
                protein_g=n.protein_g,
                carbohydrate_g=n.carbohydrate_g,
                fat_g=n.fat_g,
                saturated_fat_g=n.saturated_fat_g,
                trans_fat_g=n.trans_fat_g,
                fiber_g=n.fiber_g,
                sugar_g=n.sugar_g,
                added_sugars_g=n.added_sugars_g,
                sodium_mg=n.sodium_mg,
                potassium_mg=n.potassium_mg,
                cholesterol_mg=n.cholesterol_mg,
            ),
        )


class FoodOut(BaseModel):
    id: str
    provider: str
    name: str
    type: FoodType
    brand: str | None
    url: str | None
    default_serving_id: str | None
    servings: list[ServingOut]

    @classmethod
    def from_domain(cls, food: Food) -> "FoodOut":
        default = food.default_serving
        return cls(
            id=food.ref.external_id,
            provider=food.ref.provider,
            name=food.name,
            type=food.type,
            brand=food.brand,
            url=food.url,
            default_serving_id=default.id if default else None,
            servings=[ServingOut.from_domain(s) for s in food.servings],
        )


class FoodPageOut(BaseModel):
    items: list[FoodOut]
    page: int
    page_size: int
    total: int
    has_next: bool

    @classmethod
    def from_domain(cls, page: Page[Food]) -> "FoodPageOut":
        return cls(
            items=[FoodOut.from_domain(f) for f in page.items],
            page=page.page,
            page_size=page.page_size,
            total=page.total,
            has_next=page.has_next,
        )
