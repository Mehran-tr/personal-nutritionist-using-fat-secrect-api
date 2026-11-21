"""Password hashing (Argon2id) and access tokens (JWT)."""

import asyncio
import os
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import jwt
from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from nutritionist.core.clock import Clock
from nutritionist.core.config import AuthSettings
from nutritionist.core.ids import UserId
from nutritionist.modules.identity.domain.errors import InvalidTokenError
from nutritionist.modules.identity.domain.models import AccessToken


def default_hashing_threads() -> int:
    return max(1, (os.cpu_count() or 2) - 1)


class Argon2PasswordHasher:
    """Argon2id with library defaults (OWASP-compliant).

    Hashing runs on a *dedicated, bounded* thread pool. Running it on the event
    loop would block it outright. On the default executor (cpu_count + 4 threads)
    a login burst saturates every core and starves the event loop, which made
    unrelated requests take seconds in load tests (see PERFORMANCE.md). With
    cpu_count - 1 threads, at least one core is always left for the event loop.
    Excess logins queue, which is fine: hashing is the bottleneck anyway, and the
    per-IP auth rate limit keeps the queue short.
    """

    def __init__(self, hasher: _Argon2 | None = None, threads: int = 0) -> None:
        self._hasher = hasher or _Argon2()
        self._pool = ThreadPoolExecutor(
            max_workers=threads or default_hashing_threads(), thread_name_prefix="argon2"
        )

    async def _run[T](self, fn: Callable[..., T], *args: str) -> T:
        return await asyncio.get_running_loop().run_in_executor(self._pool, fn, *args)

    async def hash(self, password: str) -> str:
        return await self._run(self._hasher.hash, password)

    async def verify(self, password_hash: str, password: str) -> bool:
        try:
            return await self._run(self._hasher.verify, password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)


class JwtTokenService:
    """Short-lived, stateless access tokens. Refresh tokens/revocation come later,
    together with sessions, if the clients need them."""

    _REQUIRED_CLAIMS = ("exp", "iat", "sub", "iss", "aud")

    def __init__(self, settings: AuthSettings, clock: Clock) -> None:
        self._secret = settings.jwt_secret.get_secret_value()
        self._algorithm = settings.jwt_algorithm
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self._ttl = timedelta(minutes=settings.access_token_ttl_minutes)
        self._clock = clock

    def issue(self, user_id: UserId) -> AccessToken:
        now = self._clock.now()
        expires_at = now + self._ttl
        claims = {
            "sub": str(user_id),
            "iss": self._issuer,
            "aud": self._audience,
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
            "jti": uuid.uuid4().hex,
        }
        token = jwt.encode(claims, self._secret, algorithm=self._algorithm)
        return AccessToken(value=token, expires_at=expires_at)

    def verify(self, token: str) -> UserId:
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],  # pinned: never trust the token's own "alg"
                audience=self._audience,
                issuer=self._issuer,
                options={
                    "require": list(self._REQUIRED_CLAIMS),
                    # Expiry is checked below against *our* clock, so it is testable
                    # and consistent with how the token was issued.
                    "verify_exp": False,
                    "verify_iat": False,
                },
            )
            if int(claims["exp"]) <= self._clock.now().timestamp():
                raise InvalidTokenError()
            return UserId(uuid.UUID(claims["sub"]))
        except (jwt.PyJWTError, ValueError, TypeError) as exc:
            raise InvalidTokenError() from exc
