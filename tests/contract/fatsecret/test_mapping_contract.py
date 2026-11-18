"""Contract tests: recorded fatsecret payloads -> our domain model.

When you upgrade an endpoint version, record a real response into ``fixtures/``
(strip anything account-specific) and make these tests pass again.
"""

from decimal import Decimal

from nutritionist.integrations.fatsecret.schemas import FsFoodGetResponse, FsFoodsSearchResponse
from nutritionist.modules.catalog.domain.models import FoodType, SearchQuery
from nutritionist.modules.catalog.infrastructure import fatsecret_mapper as mapper
from tests.conftest import load_fixture


def test_food_get_maps_all_servings_and_nutrients() -> None:
    fs = FsFoodGetResponse.model_validate(load_fixture("food_get_v6.json")).food

    food = mapper.to_food(fs)

    assert food.ref.provider == "fatsecret"
    assert food.ref.external_id == "1641"
    assert food.type is FoodType.GENERIC
    assert len(food.servings) == 2

    default = food.default_serving
    assert default is not None
    assert default.id == "50321"  # flagged with is_default, although listed second
    assert default.metric_amount == Decimal("100.000")
    assert default.nutrients.calories_kcal == Decimal("195")
    assert default.nutrients.protein_g == Decimal("29.55")
    assert default.nutrients.sodium_mg == Decimal("394")
    assert default.nutrients.added_sugars_g is None  # absent upstream -> unknown, not zero


def test_search_maps_generic_and_brand_foods() -> None:
    fs = FsFoodsSearchResponse.model_validate(load_fixture("foods_search_v6.json")).foods_search

    page = mapper.to_page(fs, SearchQuery("chicken", page=0, page_size=2))

    assert page.total == 137
    assert page.has_next
    chicken, cheerios = page.items
    assert chicken.type is FoodType.GENERIC
    assert chicken.brand is None
    assert cheerios.type is FoodType.BRAND
    assert cheerios.brand == "General Mills"
    assert cheerios.servings[0].nutrients.fiber_g == Decimal("3.0")


def test_single_objects_and_dirty_values_are_tolerated() -> None:
    fs = FsFoodsSearchResponse.model_validate(
        load_fixture("foods_search_single_object.json")
    ).foods_search

    (food,) = mapper.to_page(fs, SearchQuery("dragon")).items

    assert food.name == "Dragon Fruit"
    (serving,) = food.servings
    assert serving.nutrients.fat_g == Decimal(0)  # "" for a required macro -> 0
    assert serving.nutrients.sodium_mg is None  # "n/a" -> unknown
    assert food.default_serving is serving  # falls back to the first serving


def test_empty_search_has_no_items() -> None:
    fs = FsFoodsSearchResponse.model_validate(load_fixture("foods_search_empty.json")).foods_search

    page = mapper.to_page(fs, SearchQuery("zzzz"))

    assert page.items == ()
    assert page.total == 0
    assert not page.has_next
