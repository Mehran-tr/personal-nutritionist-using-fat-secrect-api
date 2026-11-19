from nutritionist.core.exceptions import NotFoundError, ValidationError


class InvalidDiaryEntryError(ValidationError):
    code = "invalid_diary_entry"
    title = "Invalid diary entry"


class DiaryEntryNotFoundError(NotFoundError):
    # Also raised for other users' entries: never reveal that an id exists.
    code = "diary_entry_not_found"
    title = "Diary entry not found"


class FoodOrServingNotFoundError(NotFoundError):
    code = "food_or_serving_not_found"
    title = "Food or serving not found"
