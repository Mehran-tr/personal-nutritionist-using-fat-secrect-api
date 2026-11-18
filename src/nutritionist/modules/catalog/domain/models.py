"""Catalog domain model: provider-independent food and nutrition data.

Quantities use ``Decimal``. Floats are not acceptable for nutrition values that
are summed across a day's diary and compared to targets.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from nutritionist.modules.catalog.domain.errors import InvalidBarcodeError, InvalidSearchError

MAX_PAGE_SIZE = 50


class FoodType(StrEnum):
    GENERIC = "generic"
    BRAND = "brand"


@dataclass(frozen=True, slots=True)
class FoodRef:
    """Identifies a food at a specific provider. Stored on diary entries."""

    provider: str
    external_id: str


@dataclass(frozen=True, slots=True)
class Nutrients:
    calories_kcal: Decimal
    protein_g: Decimal
    carbohydrate_g: Decimal
    fat_g: Decimal
    saturated_fat_g: Decimal | None = None
    trans_fat_g: Decimal | None = None
    fiber_g: Decimal | None = None
    sugar_g: Decimal | None = None
    added_sugars_g: Decimal | None = None
    sodium_mg: Decimal | None = None
    potassium_mg: Decimal | None = None
    cholesterol_mg: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Serving:
    id: str
    description: str
    nutrients: Nutrients
    metric_amount: Decimal | None = None
    metric_unit: str | None = None
    number_of_units: Decimal | None = None
    measurement_description: str | None = None
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class Food:
    ref: FoodRef
    name: str
    type: FoodType
    servings: tuple[Serving, ...]
    brand: str | None = None
    url: str | None = None

    @property
    def default_serving(self) -> Serving | None:
        for serving in self.servings:
            if serving.is_default:
                return serving
        return self.servings[0] if self.servings else None


@dataclass(frozen=True, slots=True)
class Page[T]:
    items: Sequence[T]
    page: int
    page_size: int
    total: int

    @property
    def has_next(self) -> bool:
        return (self.page + 1) * self.page_size < self.total


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str
    page: int = 0
    page_size: int = 20

    def __post_init__(self) -> None:
        normalized = " ".join(self.text.split())
        if len(normalized) < 2:
            raise InvalidSearchError("Search text must be at least 2 characters.")
        if self.page < 0:
            raise InvalidSearchError("Page must be zero or positive.")
        if not 1 <= self.page_size <= MAX_PAGE_SIZE:
            raise InvalidSearchError(f"Page size must be between 1 and {MAX_PAGE_SIZE}.")
        object.__setattr__(self, "text", normalized)


@dataclass(frozen=True, slots=True)
class Gtin:
    """A product barcode, normalized to GTIN-13.

    Accepts EAN-8, UPC-A (12) and EAN-13 and validates the check digit, so we
    never spend an upstream API call on a mistyped barcode.
    """

    value: str

    _ACCEPTED_LENGTHS = (8, 12, 13)

    def __post_init__(self) -> None:
        digits = self.value.strip().replace(" ", "").replace("-", "")
        if not digits.isdigit() or len(digits) not in self._ACCEPTED_LENGTHS:
            raise InvalidBarcodeError("Barcode must be an 8, 12 or 13 digit EAN/UPC code.")
        if not self._has_valid_check_digit(digits):
            raise InvalidBarcodeError("Barcode check digit is invalid.")
        object.__setattr__(self, "value", digits.zfill(13))

    @staticmethod
    def _has_valid_check_digit(digits: str) -> bool:
        body, check = digits[:-1], int(digits[-1])
        # GS1: weights alternate 3,1,3,... starting from the rightmost body digit.
        total = sum(int(d) * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
        return (10 - total % 10) % 10 == check
