"""Pydantic models of fatsecret's JSON, exactly as they send it.

These models only validate *shape*. Turning strings into numbers and vendor
concepts into ours is the mapper's job. Quirks handled here:

* Every value is a string, even numbers.
* "Arrays" are nested under a singular key: ``servings.serving``.
* Older versions return a bare object instead of a one-item list; we normalise.
* Empty collections may come back missing, ``null`` or ``""``.
"""

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field


def _as_list(value: Any) -> Any:
    if value is None or value == "":
        return []
    if isinstance(value, dict):
        return [value]
    return value


def _empty_to_dict(value: Any) -> Any:
    return {} if value is None or value == "" else value


type ListOrSingle[T] = Annotated[list[T], BeforeValidator(_as_list)]


class _FsModel(BaseModel):
    model_config = ConfigDict(extra="ignore", coerce_numbers_to_str=True, frozen=True)


class FsServing(_FsModel):
    serving_id: str
    serving_description: str
    serving_url: str | None = None
    metric_serving_amount: str | None = None
    metric_serving_unit: str | None = None
    number_of_units: str | None = None
    measurement_description: str | None = None
    is_default: str | None = None

    calories: str | None = None
    carbohydrate: str | None = None
    protein: str | None = None
    fat: str | None = None
    saturated_fat: str | None = None
    polyunsaturated_fat: str | None = None
    monounsaturated_fat: str | None = None
    trans_fat: str | None = None
    cholesterol: str | None = None
    sodium: str | None = None
    potassium: str | None = None
    fiber: str | None = None
    sugar: str | None = None
    added_sugars: str | None = None


class FsServings(_FsModel):
    serving: ListOrSingle[FsServing] = Field(default_factory=list)


class FsFood(_FsModel):
    food_id: str
    food_name: str
    food_type: str
    brand_name: str | None = None
    food_url: str | None = None
    servings: Annotated[FsServings, BeforeValidator(_empty_to_dict)] = Field(
        default_factory=FsServings
    )


class FsFoodGetResponse(_FsModel):
    food: FsFood


class FsFoodList(_FsModel):
    food: ListOrSingle[FsFood] = Field(default_factory=list)


class FsFoodsSearch(_FsModel):
    max_results: int
    total_results: int
    page_number: int
    results: Annotated[FsFoodList, BeforeValidator(_empty_to_dict)] = Field(
        default_factory=FsFoodList
    )


class FsFoodsSearchResponse(_FsModel):
    foods_search: FsFoodsSearch


def _unwrap_value(value: Any) -> Any:
    # Documented shape is {"food_id": {"value": "123"}}; accept a bare value too.
    return value.get("value") if isinstance(value, dict) else value


class FsBarcodeResponse(_FsModel):
    food_id: Annotated[str, BeforeValidator(_unwrap_value)]


class FsErrorBody(_FsModel):
    code: int
    message: str


class FsErrorResponse(_FsModel):
    error: FsErrorBody
