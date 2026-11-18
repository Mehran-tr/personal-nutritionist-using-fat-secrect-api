from nutritionist.core.exceptions import NotFoundError, ValidationError


class InvalidProfileError(ValidationError):
    code = "invalid_profile"
    title = "Invalid profile"


class ProfileNotFoundError(NotFoundError):
    code = "profile_not_found"
    title = "Profile not set up yet"
