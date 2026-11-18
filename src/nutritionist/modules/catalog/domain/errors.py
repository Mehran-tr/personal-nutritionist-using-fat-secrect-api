from nutritionist.core.exceptions import (
    ExternalServiceError,
    ExternalServiceUnavailableError,
    NotFoundError,
    ValidationError,
)


class FoodNotFoundError(NotFoundError):
    code = "food_not_found"
    title = "Food not found"


class InvalidBarcodeError(ValidationError):
    code = "invalid_barcode"
    title = "Invalid barcode"


class InvalidSearchError(ValidationError):
    code = "invalid_search"
    title = "Invalid search"


class FoodProviderError(ExternalServiceError):
    code = "food_provider_error"
    title = "Food data provider error"


class FoodProviderUnavailableError(ExternalServiceUnavailableError):
    code = "food_provider_unavailable"
    title = "Food data provider unavailable"
