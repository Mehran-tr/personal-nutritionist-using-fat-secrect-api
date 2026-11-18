"""FastAPI dependency providers. The concrete provider is wired in ``bootstrap``;
this module only knows the port."""

from typing import Annotated

from fastapi import Depends, Request

from nutritionist.modules.catalog.application.use_cases import GetFood, LookupBarcode, SearchFoods
from nutritionist.modules.catalog.domain.ports import FoodProvider


def get_food_provider(request: Request) -> FoodProvider:
    provider: FoodProvider = request.app.state.container.food_provider
    return provider


ProviderDep = Annotated[FoodProvider, Depends(get_food_provider)]


def search_foods_use_case(provider: ProviderDep) -> SearchFoods:
    return SearchFoods(provider)


def get_food_use_case(provider: ProviderDep) -> GetFood:
    return GetFood(provider)


def lookup_barcode_use_case(provider: ProviderDep) -> LookupBarcode:
    return LookupBarcode(provider)
