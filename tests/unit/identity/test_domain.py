import pytest

from nutritionist.modules.identity.domain.errors import InvalidEmailError, WeakPasswordError
from nutritionist.modules.identity.domain.models import Email, PlainPassword, User
from tests.fakes import NOW


def test_email_is_normalised() -> None:
    assert Email("  Mehran@Example.COM ").value == "mehran@example.com"
    assert Email("a@b.de") == Email("A@B.DE")


@pytest.mark.parametrize(
    "raw", ["", "no-at-sign", "@example.com", "user@localhost", "a" * 320 + "@x.de"]
)
def test_invalid_email(raw: str) -> None:
    with pytest.raises(InvalidEmailError):
        Email(raw)


@pytest.mark.parametrize("raw", ["short", " leading-space-pw", "trailing-space-pw ", "x" * 129])
def test_password_policy(raw: str) -> None:
    with pytest.raises(WeakPasswordError):
        PlainPassword(raw)


def test_secrets_never_appear_in_repr() -> None:
    password = PlainPassword("correct horse battery")
    user = User.register(Email("a@b.de"), "argon2-hash-value", NOW)

    assert "correct horse" not in repr(password)
    assert "argon2-hash-value" not in repr(user)


def test_register_assigns_new_ids() -> None:
    first = User.register(Email("a@b.de"), "h", NOW)
    second = User.register(Email("a@b.de"), "h", NOW)
    assert first.id != second.id
    assert first.is_active
