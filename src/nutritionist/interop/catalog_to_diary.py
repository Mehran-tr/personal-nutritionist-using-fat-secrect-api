"""Catalog seen through the diary's ``FoodLookup`` port."""

from nutritionist.modules.catalog.application.use_cases import GetFood
from nutritionist.modules.catalog.domain.errors import FoodNotFoundError
from nutritionist.modules.diary.domain.models import LoggedFood, NutrientAmounts


class CatalogFoodLookup:
    def __init__(self, get_food: GetFood) -> None:
        self._get_food = get_food

    async def find(self, food_id: str, serving_id: str) -> LoggedFood | None:
        try:
            food = await self._get_food.execute(food_id)
        except FoodNotFoundError:
            return None
        # Upstream outages (FoodProviderUnavailableError) propagate on purpose:
        # the client gets a 503 and can retry; we never log a half-known food.

        serving = next((s for s in food.servings if s.id == serving_id), None)
        if serving is None:
            return None

        n = serving.nutrients
        return LoggedFood(
            provider=food.ref.provider,
            food_id=food.ref.external_id,
            food_name=food.name,
            brand=food.brand,
            serving_id=serving.id,
            serving_description=serving.description,
            per_serving=NutrientAmounts(
                calories_kcal=n.calories_kcal,
                protein_g=n.protein_g,
                carbohydrate_g=n.carbohydrate_g,
                fat_g=n.fat_g,
                fiber_g=n.fiber_g,
                sugar_g=n.sugar_g,
                saturated_fat_g=n.saturated_fat_g,
                sodium_mg=n.sodium_mg,
            ),
        )
