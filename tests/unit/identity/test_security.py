from datetime import timedelta

import jwt
import pytest
from argon2 import PasswordHasher

from nutritionist.core.clock import FixedClock
from nutritionist.core.config import AuthSettings
from nutritionist.core.ids import new_user_id
from nutritionist.modules.identity.domain.errors import InvalidTokenError
from nutritionist.modules.identity.infrastructure.security import (
    Argon2PasswordHasher,
    JwtTokenService,
)
from tests.fakes import NOW


@pytest.fixture
def tokens(auth_settings: AuthSettings) -> JwtTokenService:
    return JwtTokenService(auth_settings, FixedClock(NOW))


class TestJwtTokenService:
    def test_round_trip(self, tokens: JwtTokenService) -> None:
        user_id = new_user_id()
        token = tokens.issue(user_id)

        assert tokens.verify(token.value) == user_id
        assert token.expires_at == NOW + timedelta(minutes=30)

    def test_expired_token_is_rejected(self, auth_settings: AuthSettings) -> None:
        token = JwtTokenService(auth_settings, FixedClock(NOW)).issue(new_user_id())
        later = JwtTokenService(auth_settings, FixedClock(NOW + timedelta(minutes=31)))

        with pytest.raises(InvalidTokenError):
            later.verify(token.value)

    @pytest.mark.parametrize(
        "mutate",
        [
            pytest.param(
                lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"), id="tampered"
            ),
            pytest.param(lambda t: "not-a-jwt", id="garbage"),
        ],
    )
    def test_invalid_tokens_are_rejected(self, tokens: JwtTokenService, mutate: object) -> None:
        token = tokens.issue(new_user_id()).value
        with pytest.raises(InvalidTokenError):
            tokens.verify(mutate(token))  # type: ignore[operator]

    @pytest.mark.parametrize(
        ("claims_override", "key", "algorithm"),
        [
            pytest.param({"aud": "someone-else"}, None, "HS256", id="wrong-audience"),
            pytest.param({"iss": "evil"}, None, "HS256", id="wrong-issuer"),
            pytest.param({}, "another-secret-of-sufficient-length!!", "HS256", id="wrong-key"),
            pytest.param({}, None, "none", id="alg-none"),
        ],
    )
    def test_forged_tokens_are_rejected(
        self,
        tokens: JwtTokenService,
        auth_settings: AuthSettings,
        claims_override: dict[str, str],
        key: str | None,
        algorithm: str,
    ) -> None:
        claims = {
            "sub": str(new_user_id()),
            "iss": auth_settings.jwt_issuer,
            "aud": auth_settings.jwt_audience,
            "iat": int(NOW.timestamp()),
            "exp": int((NOW + timedelta(minutes=5)).timestamp()),
            **claims_override,
        }
        secret = key or auth_settings.jwt_secret.get_secret_value()
        forged = jwt.encode(claims, None if algorithm == "none" else secret, algorithm=algorithm)

        with pytest.raises(InvalidTokenError):
            tokens.verify(forged)


class TestArgon2PasswordHasher:
    # Cheap parameters keep the suite fast; production uses library defaults.
    hasher = Argon2PasswordHasher(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1))

    async def test_hash_and_verify(self) -> None:
        password_hash = await self.hasher.hash("correct horse battery")

        assert password_hash.startswith("$argon2id$")
        assert await self.hasher.verify(password_hash, "correct horse battery")
        assert not await self.hasher.verify(password_hash, "wrong")

    async def test_garbage_hash_is_a_failed_verification_not_a_crash(self) -> None:
        assert not await self.hasher.verify("not-a-hash", "whatever")

    async def test_weaker_parameters_need_rehash(self) -> None:
        weak_hash = await self.hasher.hash("pw")
        assert Argon2PasswordHasher().needs_rehash(weak_hash)
