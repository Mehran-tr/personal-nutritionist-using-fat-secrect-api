"""End-to-end through the real app (middleware, routing, errors, serialization),
with the food provider swapped for a fake at the composition root."""

import pytest
from fastapi.testclient import TestClient

from nutritionist.modules.catalog.domain.errors import FoodProviderUnavailableError
from tests.fakes import FakeFoodProvider


@pytest.fixture
def client(authed_client: TestClient) -> TestClient:
    """Catalog endpoints require a logged-in user (they spend fatsecret quota)."""
    return authed_client


def test_health(client: TestClient) -> None:
    assert client.get("/health/live").json() == {"status": "ok", "checks": {}}
    assert client.get("/health/ready").json() == {
        "status": "ok",
        "checks": {"database": True, "cache": True},
    }


def test_search_foods(client: TestClient) -> None:
    response = client.get("/api/v1/foods", params={"q": "apple", "page_size": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["has_next"] is True
    (item,) = body["items"]
    assert item["name"] == "Apple"
    assert item["default_serving_id"] == "1-100g"
    nutrients = item["servings"][0]["nutrients"]
    assert nutrients["calories_kcal"] == 52  # Decimal travels as a JSON number
    assert nutrients["sodium_mg"] is None


def test_get_food_and_request_id_propagation(client: TestClient) -> None:
    response = client.get("/api/v1/foods/1", headers={"x-request-id": "abc123"})

    assert response.status_code == 200
    assert response.json()["id"] == "1"
    assert response.headers["x-request-id"] == "abc123"


def test_barcode_lookup(client: TestClient) -> None:
    response = client.get("/api/v1/foods/barcode/4006381333931")
    assert response.status_code == 200
    assert response.json()["name"] == "Apple"


@pytest.mark.parametrize(
    ("path", "status", "problem_type"),
    [
        ("/api/v1/foods/404", 404, "/problems/food_not_found"),
        ("/api/v1/foods/barcode/4006381333932", 422, "/problems/invalid_barcode"),
        ("/api/v1/foods?q=a", 422, "/problems/request_validation_error"),
        ("/api/v1/nope", 404, "/problems/http_error"),
    ],
)
def test_errors_are_problem_json(
    client: TestClient, path: str, status: int, problem_type: str
) -> None:
    response = client.get(path)

    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"
    body = response.json()
    assert body["type"] == problem_type
    assert body["status"] == status
    assert body["request_id"]


def test_upstream_outage_is_503(client: TestClient, provider: FakeFoodProvider) -> None:
    provider.error = FoodProviderUnavailableError()

    response = client.get("/api/v1/foods/1")

    assert response.status_code == 503
    assert response.json()["type"] == "/problems/food_provider_unavailable"
