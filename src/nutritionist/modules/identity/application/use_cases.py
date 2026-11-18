from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from nutritionist.core.clock import Clock
from nutritionist.core.exceptions import ValidationError
from nutritionist.core.ids import UserId
from nutritionist.core.uow import UnitOfWork
from nutritionist.modules.identity.domain.errors import (
    AccountUnavailableError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
)
from nutritionist.modules.identity.domain.models import AccessToken, Email, PlainPassword, User
from nutritionist.modules.identity.domain.ports import PasswordHasher, TokenService, UserRepository


class IdentityUnitOfWork(UnitOfWork, Protocol):
    @property
    def users(self) -> UserRepository: ...


IdentityUowFactory = Callable[[], IdentityUnitOfWork]


@dataclass(frozen=True, slots=True)
class RegisterUser:
    uow: IdentityUowFactory
    hasher: PasswordHasher
    clock: Clock

    async def execute(self, email: str, password: str) -> User:
        address = Email(email)
        secret = PlainPassword(password)
        password_hash = await self.hasher.hash(secret.value)

        async with self.uow() as uow:
            if await uow.users.get_by_email(address) is not None:
                raise EmailAlreadyRegisteredError()
            user = User.register(address, password_hash, self.clock.now())
            uow.users.add(user)
            await uow.commit()  # a concurrent duplicate is caught by the unique index
        return user


@dataclass(slots=True)
class AuthenticateUser:
    uow: IdentityUowFactory
    hasher: PasswordHasher
    tokens: TokenService
    _dummy_hash: str | None = field(default=None, init=False)

    async def execute(self, email: str, password: str) -> AccessToken:
        try:
            address = Email(email)
        except ValidationError as exc:
            raise InvalidCredentialsError() from exc

        async with self.uow() as uow:
            user = await uow.users.get_by_email(address)
            if user is None:
                # Spend the same time as a real check so response timing
                # does not reveal which emails are registered.
                await self.hasher.verify(await self._dummy(), password)
                raise InvalidCredentialsError()

            if not await self.hasher.verify(user.password_hash, password):
                raise InvalidCredentialsError()
            if not user.is_active:
                raise AccountUnavailableError()

            if self.hasher.needs_rehash(user.password_hash):
                await uow.users.update(user.with_password_hash(await self.hasher.hash(password)))
                await uow.commit()

        return self.tokens.issue(user.id)

    async def _dummy(self) -> str:
        if self._dummy_hash is None:
            self._dummy_hash = await self.hasher.hash("timing-equaliser-password")
        return self._dummy_hash


@dataclass(frozen=True, slots=True)
class GetCurrentUser:
    uow: IdentityUowFactory

    async def execute(self, user_id: UserId) -> User:
        async with self.uow() as uow:
            user = await uow.users.get(user_id)
        if user is None or not user.is_active:
            raise AccountUnavailableError()
        return user


@dataclass(frozen=True, slots=True)
class IdentityUseCases:
    """The module's public application API, assembled once in ``bootstrap``."""

    register_user: RegisterUser
    authenticate_user: AuthenticateUser
    get_current_user: GetCurrentUser
