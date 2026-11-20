from nutritionist.core.exceptions import (
    AuthenticationError,
    ConflictError,
    TooManyRequestsError,
    ValidationError,
)


class InvalidEmailError(ValidationError):
    code = "invalid_email"
    title = "Invalid email address"


class WeakPasswordError(ValidationError):
    code = "weak_password"
    title = "Password does not meet the policy"


class EmailAlreadyRegisteredError(ConflictError):
    code = "email_already_registered"
    title = "Email already registered"


class InvalidCredentialsError(AuthenticationError):
    # Deliberately identical for "unknown email" and "wrong password" (no user enumeration).
    code = "invalid_credentials"
    title = "Invalid email or password"


class InvalidTokenError(AuthenticationError):
    code = "invalid_token"
    title = "Invalid or expired access token"


class AccountUnavailableError(AuthenticationError):
    code = "account_unavailable"
    title = "Account is disabled or no longer exists"


class TooManyLoginAttemptsError(TooManyRequestsError):
    code = "too_many_login_attempts"
    title = "Too many failed login attempts"
