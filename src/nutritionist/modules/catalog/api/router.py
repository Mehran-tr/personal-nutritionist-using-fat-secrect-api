from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from nutritionist.api.security import CurrentUserId
from nutritionist.modules.catalog.api.deps import (
    get_food_use_case,
    lookup_barcode_use_case,
    search_foods_use_case,
)
from nutritionist.modules.catalog.api.schemas import FoodOut, FoodPageOut
from nutritionist.modules.catalog.application.use_cases import GetFood, LookupBarcode, SearchFoods
from nutritionist.modules.catalog.domain.models import MAX_PAGE_SIZE

# Authenticated even though the data isn't personal: every call can spend paid
# fatsecret quota, so anonymous callers must not be able to drive it.
router = APIRouter(prefix="/foods", tags=["catalog"])


@router.get("", response_model=FoodPageOut, summary="Search the food database")
async def search_foods(
    _user: CurrentUserId,
    use_case: Annotated[SearchFoods, Depends(search_foods_use_case)],
    q: Annotated[str, Query(min_length=2, max_length=100, description="Search text")],
    page: Annotated[int, Query(ge=0, description="Zero-based page")] = 0,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> FoodPageOut:
    result = await use_case.execute(q, page=page, page_size=page_size)
    return FoodPageOut.from_domain(result)


@router.get(
    "/barcode/{barcode}", response_model=FoodOut, summary="Look up a food by EAN/UPC barcode"
)
async def lookup_barcode(
    _user: CurrentUserId,
    use_case: Annotated[LookupBarcode, Depends(lookup_barcode_use_case)],
    barcode: Annotated[str, Path(min_length=8, max_length=14)],
) -> FoodOut:
    return FoodOut.from_domain(await use_case.execute(barcode))


@router.get("/{food_id}", response_model=FoodOut, summary="Get a food with all its servings")
async def get_food(
    _user: CurrentUserId,
    use_case: Annotated[GetFood, Depends(get_food_use_case)],
    food_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,40}$")],
) -> FoodOut:
    return FoodOut.from_domain(await use_case.execute(food_id))
