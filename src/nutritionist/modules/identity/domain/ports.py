from typing import Protocol

from nutritionist.core.ids import UserId
from nutritionist.modules.identity.domain.models import AccessToken, Email, User


class UserRepository(Protocol):
    async def get(self, user_id: UserId) -> User | None: ...

    async def get_by_email(self, email: Email) -> User | None: ...

    def add(self, user: User) -> None: ...

    async def update(self, user: User) -> None: ...


class PasswordHasher(Protocol):
    """Async on purpose: good hashes are slow CPU work and must not block the event loop."""

    async def hash(self, password: str) -> str: ...

    async def verify(self, password_hash: str, password: str) -> bool: ...

    def needs_rehash(self, password_hash: str) -> bool: ...


class TokenService(Protocol):
    def issue(self, user_id: UserId) -> AccessToken: ...

    def verify(self, token: str) -> UserId: ...
