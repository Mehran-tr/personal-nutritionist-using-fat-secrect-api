import pytest

from nutritionist.core.clock import FixedClock
from nutritionist.core.rate_limit_stores import InMemoryRateLimiter
from nutritionist.modules.identity.application.use_cases import (
    AuthenticateUser,
    LoginGuard,
    LoginPolicy,
    RegisterUser,
)
from nutritionist.modules.identity.domain.errors import (
    InvalidCredentialsError,
    TooManyLoginAttemptsError,
)
from tests.fakes import NOW, FakePasswordHasher, FakeTokenService, FakeUnitOfWork

PASSWORD = "correct horse battery"
POLICY = LoginPolicy(
    max_failures_per_account_and_ip=3,
    lockout_seconds=900,
    max_failures_per_account=5,
    account_window_seconds=3600,
)


@pytest.fixture
async def login() -> tuple[AuthenticateUser, FakePasswordHasher]:
    uow, hasher = FakeUnitOfWork(), FakePasswordHasher()
    await RegisterUser(uow, hasher, FixedClock(NOW)).execute("a@b.de", PASSWORD)
    guard = LoginGuard(InMemoryRateLimiter(), POLICY)
    return AuthenticateUser(uow, hasher, FakeTokenService(), guard), hasher


async def _fail(use_case: AuthenticateUser, ip: str, times: int) -> None:
    for _ in range(times):
        with pytest.raises(InvalidCredentialsError):
            await use_case.execute("a@b.de", "wrong password!", ip)


async def test_ip_is_jailed_after_max_retries_even_with_the_right_password(
    login: tuple[AuthenticateUser, FakePasswordHasher],
) -> None:
    use_case, hasher = login
    await _fail(use_case, "1.1.1.1", 3)
    calls_before = hasher.verify_calls

    with pytest.raises(TooManyLoginAttemptsError) as exc_info:
        await use_case.execute("A@B.de", PASSWORD, "1.1.1.1")  # email case doesn't bypass

    assert exc_info.value.retry_after_seconds > 0
    assert hasher.verify_calls == calls_before  # rejected before any hashing work


async def test_lockout_is_per_ip_so_attackers_cannot_lock_out_the_owner(
    login: tuple[AuthenticateUser, FakePasswordHasher],
) -> None:
    use_case, _ = login
    await _fail(use_case, "6.6.6.6", 3)
    assert await use_case.execute("a@b.de", PASSWORD, "2.2.2.2")


async def test_distributed_guessing_locks_the_account_for_everyone(
    login: tuple[AuthenticateUser, FakePasswordHasher],
) -> None:
    use_case, _ = login
    for i in range(5):
        await _fail(use_case, f"10.0.0.{i}", 1)
    with pytest.raises(TooManyLoginAttemptsError):
        await use_case.execute("a@b.de", PASSWORD, "2.2.2.2")


async def test_success_resets_the_ip_counter(
    login: tuple[AuthenticateUser, FakePasswordHasher],
) -> None:
    use_case, _ = login
    await _fail(use_case, "1.1.1.1", 2)
    await use_case.execute("a@b.de", PASSWORD, "1.1.1.1")
    await _fail(use_case, "1.1.1.1", 2)  # would be locked at 3 without the reset
    assert await use_case.execute("a@b.de", PASSWORD, "1.1.1.1")


async def test_unknown_accounts_are_throttled_too(
    login: tuple[AuthenticateUser, FakePasswordHasher],
) -> None:
    use_case, _ = login
    for _ in range(3):
        with pytest.raises(InvalidCredentialsError):
            await use_case.execute("ghost@b.de", PASSWORD, "1.1.1.1")
    with pytest.raises(TooManyLoginAttemptsError):
        await use_case.execute("ghost@b.de", PASSWORD, "1.1.1.1")
