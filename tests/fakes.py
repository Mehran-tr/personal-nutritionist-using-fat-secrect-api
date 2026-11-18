"""In-memory test doubles and factories. Prefer these over mocks."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import TracebackType
from typing import Self

from nutritionist.core.ids import UserId
from nutritionist.modules.catalog.domain.models import (
    Food,
    FoodRef,
    FoodType,
    Gtin,
    Nutrients,
    Page,
    SearchQuery,
    Serving,
)
from nutritionist.modules.identity.domain.models import AccessToken, Email, User
from nutritionist.modules.profile.domain.models import Profile


def make_food(external_id: str = "1", name: str = "Apple", *, kcal: str = "52") -> Food:
    return Food(
        ref=FoodRef(provider="fake", external_id=external_id),
        name=name,
        type=FoodType.GENERIC,
        servings=(
            Serving(
                id=f"{external_id}-100g",
                description="100 g",
                metric_amount=Decimal("100"),
                metric_unit="g",
                is_default=True,
                nutrients=Nutrients(
                    calories_kcal=Decimal(kcal),
                    protein_g=Decimal("0.3"),
                    carbohydrate_g=Decimal("13.8"),
                    fat_g=Decimal("0.2"),
                    fiber_g=Decimal("2.4"),
                ),
            ),
        ),
    )


@dataclass
class FakeFoodProvider:
    foods: dict[str, Food] = field(default_factory=dict)
    barcodes: dict[str, str] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    error: Exception | None = None

    async def search(self, query: SearchQuery) -> Page[Food]:
        self._record(f"search:{query.text}:{query.page}")
        matches = [f for f in self.foods.values() if query.text.lower() in f.name.lower()]
        start = query.page * query.page_size
        return Page(
            items=tuple(matches[start : start + query.page_size]),
            page=query.page,
            page_size=query.page_size,
            total=len(matches),
        )

    async def get(self, external_id: str) -> Food | None:
        self._record(f"get:{external_id}")
        return self.foods.get(external_id)

    async def find_by_barcode(self, barcode: Gtin) -> Food | None:
        self._record(f"barcode:{barcode.value}")
        food_id = self.barcodes.get(barcode.value)
        return self.foods.get(food_id) if food_id else None

    def _record(self, call: str) -> None:
        self.calls.append(call)
        if self.error is not None:
            raise self.error


# ---------------------------------------------------------------- identity & profile

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[UserId, User] = {}

    async def get(self, user_id: UserId) -> User | None:
        return self.users.get(user_id)

    async def get_by_email(self, email: Email) -> User | None:
        return next((u for u in self.users.values() if u.email == email), None)

    def add(self, user: User) -> None:
        self.users[user.id] = user

    async def update(self, user: User) -> None:
        self.users[user.id] = user


class FakeProfileRepository:
    def __init__(self) -> None:
        self.profiles: dict[UserId, Profile] = {}

    async def get(self, user_id: UserId) -> Profile | None:
        return self.profiles.get(user_id)

    async def save(self, profile: Profile) -> None:
        self.profiles[profile.user_id] = profile


class FakeUnitOfWork:
    """Shared by both modules' use cases; records commits for assertions."""

    def __init__(self) -> None:
        self.users = FakeUserRepository()
        self.profiles = FakeProfileRepository()
        self.commits = 0

    def __call__(self) -> Self:  # acts as its own factory
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


class FakePasswordHasher:
    def __init__(self, *, needs_rehash: bool = False) -> None:
        self._needs_rehash = needs_rehash
        self.verify_calls = 0

    async def hash(self, password: str) -> str:
        return f"hashed:{password}"

    async def verify(self, password_hash: str, password: str) -> bool:
        self.verify_calls += 1
        return password_hash == f"hashed:{password}"

    def needs_rehash(self, password_hash: str) -> bool:
        return self._needs_rehash


class FakeTokenService:
    def issue(self, user_id: UserId) -> AccessToken:
        return AccessToken(value=f"token-for-{user_id}", expires_at=NOW + timedelta(minutes=30))

    def verify(self, token: str) -> UserId:
        raise NotImplementedError
