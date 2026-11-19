from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from nutritionist.bootstrap import Container, build_container
from nutritionist.core.config import Settings
from nutritionist.main import create_app
from tests.fakes import FakeFoodProvider, make_food


@pytest.fixture
def provider() -> FakeFoodProvider:
    return FakeFoodProvider(
        foods={"1": make_food("1", "Apple"), "2": make_food("2", "Apple pie", kcal="237")},
        barcodes={"4006381333931": "1"},
    )


@pytest.fixture
def client(settings: Settings, provider: FakeFoodProvider, database: None) -> Iterator[TestClient]:
    async def factory(s: Settings) -> Container:
        # The only fake: no real fatsecret calls. Everything else is the real app.
        return await build_container(s, food_provider=provider)

    with TestClient(create_app(settings, container_factory=factory)) as test_client:
        yield test_client
