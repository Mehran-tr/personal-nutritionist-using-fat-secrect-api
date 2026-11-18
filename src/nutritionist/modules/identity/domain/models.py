from dataclasses import dataclass, field, replace
from datetime import datetime

from nutritionist.core.ids import UserId, new_user_id
from nutritionist.modules.identity.domain.errors import InvalidEmailError, WeakPasswordError

MAX_EMAIL_LENGTH = 320
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128  # bounds hashing cost; prevents long-password DoS


@dataclass(frozen=True, slots=True)
class Email:
    """Normalised (trimmed, lower-cased) address. Format is checked at the API edge;
    here we only enforce what the domain relies on: uniqueness by normalised value."""

    value: str

    def __post_init__(self) -> None:
        normalised = self.value.strip().lower()
        local, _, domain = normalised.partition("@")
        if not local or "." not in domain or len(normalised) > MAX_EMAIL_LENGTH:
            raise InvalidEmailError("Email address is not valid.")
        object.__setattr__(self, "value", normalised)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PlainPassword:
    value: str = field(repr=False)  # never ends up in logs or tracebacks

    def __post_init__(self) -> None:
        if not MIN_PASSWORD_LENGTH <= len(self.value) <= MAX_PASSWORD_LENGTH:
            raise WeakPasswordError(
                f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters long."
            )
        if self.value.strip() != self.value or not self.value.strip():
            raise WeakPasswordError("Password must not start or end with whitespace.")


@dataclass(frozen=True, slots=True)
class User:
    id: UserId
    email: Email
    password_hash: str = field(repr=False)
    created_at: datetime
    is_active: bool = True

    @classmethod
    def register(cls, email: Email, password_hash: str, now: datetime) -> "User":
        return cls(id=new_user_id(), email=email, password_hash=password_hash, created_at=now)

    def with_password_hash(self, password_hash: str) -> "User":
        return replace(self, password_hash=password_hash)


@dataclass(frozen=True, slots=True)
class AccessToken:
    value: str = field(repr=False)
    expires_at: datetime
    token_type: str = "bearer"
