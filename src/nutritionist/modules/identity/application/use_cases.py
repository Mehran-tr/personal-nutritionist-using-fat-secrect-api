import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from nutritionist.core.clock import Clock
from nutritionist.core.exceptions import ValidationError
from nutritionist.core.ids import UserId
from nutritionist.core.rate_limit import RateLimiter
from nutritionist.core.uow import UnitOfWork
from nutritionist.modules.identity.domain.errors import (
    AccountUnavailableError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    TooManyLoginAttemptsError,
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


@dataclass(frozen=True, slots=True)
class LoginPolicy:
    max_failures_per_account_and_ip: int = 5
    lockout_seconds: int = 15 * 60
    max_failures_per_account: int = 20
    account_window_seconds: int = 60 * 60


@dataclass(frozen=True, slots=True)
class LoginGuard:
    """Max-retry and lockout ("jail") for logins.

    Two counters, both keyed by a hash of the email (no addresses in Redis):
    * account + IP: 5 failures -> that IP is locked out of that account for 15 min.
      Locking per IP means an attacker can't lock the real owner out from elsewhere.
    * account (any IP): 20 failures per hour -> account locked for everyone until
      the window ends. This stops distributed guessing across many IPs.
    """

    limiter: RateLimiter
    policy: LoginPolicy = LoginPolicy()

    async def check(self, email: str, client_ip: str) -> None:
        pair_key, account_key = self._keys(email, client_ip)
        for key, limit in (
            (pair_key, self.policy.max_failures_per_account_and_ip),
            (account_key, self.policy.max_failures_per_account),
        ):
            state = await self.limiter.peek(key)
            if state.count >= limit:
                raise TooManyLoginAttemptsError(
                    "Too many failed attempts. Try again later.",
                    retry_after_seconds=state.retry_after_seconds,
                )

    async def record_failure(self, email: str, client_ip: str) -> None:
        pair_key, account_key = self._keys(email, client_ip)
        await self.limiter.hit(pair_key, self.policy.lockout_seconds)
        await self.limiter.hit(account_key, self.policy.account_window_seconds)

    async def record_success(self, email: str, client_ip: str) -> None:
        pair_key, _ = self._keys(email, client_ip)
        await self.limiter.reset(pair_key)

    @staticmethod
    def _keys(email: str, client_ip: str) -> tuple[str, str]:
        account = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:32]
        return f"login:{account}:{client_ip}", f"login:{account}"


@dataclass(slots=True)
class AuthenticateUser:
    uow: IdentityUowFactory
    hasher: PasswordHasher
    tokens: TokenService
    guard: LoginGuard
    _dummy_hash: str | None = field(default=None, init=False)

    async def execute(self, email: str, password: str, client_ip: str) -> AccessToken:
        # Locked out? Reject before spending any hashing time.
        await self.guard.check(email, client_ip)
        try:
            token = await self._authenticate(email, password)
        except InvalidCredentialsError:
            await self.guard.record_failure(email, client_ip)
            raise
        await self.guard.record_success(email, client_ip)
        return token

    async def _authenticate(self, email: str, password: str) -> AccessToken:
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
