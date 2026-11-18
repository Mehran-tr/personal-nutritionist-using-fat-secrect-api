"""Anti-corruption layer: fatsecret JSON models -> catalog domain models."""

from decimal import Decimal, InvalidOperation

from nutritionist.integrations.fatsecret.schemas import FsFood, FsFoodsSearch, FsServing
from nutritionist.modules.catalog.domain.models import (
    Food,
    FoodRef,
    FoodType,
    Nutrients,
    Page,
    SearchQuery,
    Serving,
)

PROVIDER = "fatsecret"
_ZERO = Decimal(0)


def to_food(fs: FsFood) -> Food:
    return Food(
        ref=FoodRef(provider=PROVIDER, external_id=fs.food_id),
        name=fs.food_name.strip(),
        type=FoodType.BRAND if fs.food_type.lower() == "brand" else FoodType.GENERIC,
        brand=(fs.brand_name or "").strip() or None,
        url=fs.food_url,
        servings=tuple(to_serving(s) for s in fs.servings.serving),
    )


def to_serving(fs: FsServing) -> Serving:
    return Serving(
        id=fs.serving_id,
        description=fs.serving_description,
        metric_amount=_decimal(fs.metric_serving_amount),
        metric_unit=fs.metric_serving_unit or None,
        number_of_units=_decimal(fs.number_of_units),
        measurement_description=fs.measurement_description or None,
        is_default=fs.is_default == "1",
        nutrients=Nutrients(
            # The four macros are always present upstream. Default to zero defensively
            # instead of failing a whole search because of one incomplete serving.
            calories_kcal=_decimal(fs.calories) or _ZERO,
            protein_g=_decimal(fs.protein) or _ZERO,
            carbohydrate_g=_decimal(fs.carbohydrate) or _ZERO,
            fat_g=_decimal(fs.fat) or _ZERO,
            saturated_fat_g=_decimal(fs.saturated_fat),
            trans_fat_g=_decimal(fs.trans_fat),
            fiber_g=_decimal(fs.fiber),
            sugar_g=_decimal(fs.sugar),
            added_sugars_g=_decimal(fs.added_sugars),
            sodium_mg=_decimal(fs.sodium),
            potassium_mg=_decimal(fs.potassium),
            cholesterol_mg=_decimal(fs.cholesterol),
        ),
    )


def to_page(fs: FsFoodsSearch, query: SearchQuery) -> Page[Food]:
    return Page(
        items=tuple(to_food(f) for f in fs.results.food),
        page=query.page,
        page_size=query.page_size,
        total=fs.total_results,
    )


def _decimal(raw: str | None) -> Decimal | None:
    if raw is None or raw.strip() == "":
        return None
    try:
        value = Decimal(raw.strip())
    except InvalidOperation:
        return None
    return value if value.is_finite() else None
