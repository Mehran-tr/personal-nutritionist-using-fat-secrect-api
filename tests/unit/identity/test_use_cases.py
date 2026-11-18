from dataclasses import replace

import pytest

from nutritionist.core.clock import FixedClock
from nutritionist.core.ids import new_user_id
from nutritionist.modules.identity.application.use_cases import (
    AuthenticateUser,
    GetCurrentUser,
    RegisterUser,
)
from nutritionist.modules.identity.domain.errors import (
    AccountUnavailableError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidEmailError,
    WeakPasswordError,
)
from nutritionist.modules.identity.domain.models import Email
from tests.fakes import NOW, FakePasswordHasher, FakeTokenService, FakeUnitOfWork

PASSWORD = "correct horse battery"


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def hasher() -> FakePasswordHasher:
    return FakePasswordHasher()


async def _register(uow: FakeUnitOfWork, hasher: FakePasswordHasher, email: str = "a@b.de") -> None:
    await RegisterUser(uow, hasher, FixedClock(NOW)).execute(email, PASSWORD)


class TestRegisterUser:
    async def test_stores_hashed_password_and_commits(
        self, uow: FakeUnitOfWork, hasher: FakePasswordHasher
    ) -> None:
        user = await RegisterUser(uow, hasher, FixedClock(NOW)).execute(" A@B.de ", PASSWORD)

        assert user.email == Email("a@b.de")
        assert user.password_hash == f"hashed:{PASSWORD}"
        assert user.created_at == NOW
        assert uow.users.users[user.id] == user
        assert uow.commits == 1

    async def test_rejects_duplicate_email_case_insensitively(
        self, uow: FakeUnitOfWork, hasher: FakePasswordHasher
    ) -> None:
        await _register(uow, hasher, "a@b.de")
        with pytest.raises(EmailAlreadyRegisteredError):
            await _register(uow, hasher, "A@B.DE")

    @pytest.mark.parametrize(
        ("email", "password", "error"),
        [("nope", PASSWORD, InvalidEmailError), ("a@b.de", "short", WeakPasswordError)],
    )
    async def test_validates_before_touching_storage(
        self,
        uow: FakeUnitOfWork,
        hasher: FakePasswordHasher,
        email: str,
        password: str,
        error: type[Exception],
    ) -> None:
        with pytest.raises(error):
            await RegisterUser(uow, hasher, FixedClock(NOW)).execute(email, password)
        assert uow.commits == 0


class TestAuthenticateUser:
    async def test_issues_token_for_valid_credentials(
        self, uow: FakeUnitOfWork, hasher: FakePasswordHasher
    ) -> None:
        await _register(uow, hasher)
        token = await AuthenticateUser(uow, hasher, FakeTokenService()).execute("a@b.de", PASSWORD)
        assert token.value.startswith("token-for-")

    @pytest.mark.parametrize(
        ("email", "password"),
        [("a@b.de", "wrong password!"), ("other@b.de", PASSWORD), ("not-an-email", PASSWORD)],
    )
    async def test_every_failure_looks_the_same(
        self, uow: FakeUnitOfWork, hasher: FakePasswordHasher, email: str, password: str
    ) -> None:
        await _register(uow, hasher)
        with pytest.raises(InvalidCredentialsError):
            await AuthenticateUser(uow, hasher, FakeTokenService()).execute(email, password)

    async def test_unknown_email_still_spends_a_hash_verification(
        self, uow: FakeUnitOfWork, hasher: FakePasswordHasher
    ) -> None:
        with pytest.raises(InvalidCredentialsError):
            await AuthenticateUser(uow, hasher, FakeTokenService()).execute("x@b.de", PASSWORD)
        assert hasher.verify_calls == 1

    async def test_inactive_account_is_refused(
        self, uow: FakeUnitOfWork, hasher: FakePasswordHasher
    ) -> None:
        await _register(uow, hasher)
        (user,) = uow.users.users.values()
        uow.users.users[user.id] = replace(user, is_active=False)

        with pytest.raises(AccountUnavailableError):
            await AuthenticateUser(uow, hasher, FakeTokenService()).execute("a@b.de", PASSWORD)

    async def test_outdated_hash_is_upgraded_on_login(self, uow: FakeUnitOfWork) -> None:
        await _register(uow, FakePasswordHasher())
        commits_before = uow.commits

        await AuthenticateUser(
            uow, FakePasswordHasher(needs_rehash=True), FakeTokenService()
        ).execute("a@b.de", PASSWORD)

        assert uow.commits == commits_before + 1


async def test_get_current_user_refuses_deleted_accounts(uow: FakeUnitOfWork) -> None:
    with pytest.raises(AccountUnavailableError):
        await GetCurrentUser(uow).execute(new_user_id())
