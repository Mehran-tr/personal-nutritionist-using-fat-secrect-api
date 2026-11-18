"""The account journey through the real app and a real database."""

from typing import Any

import pytest
from fastapi.testclient import TestClient

PASSWORD = "correct horse battery"
PROFILE: dict[str, Any] = {
    "sex": "female",
    "birth_date": "1994-06-15",
    "height_cm": 168,
    "weight_kg": 64.25,
    "activity_level": "moderate",
    "goal": "maintain",
    "dietary_preferences": ["vegetarian", "dairy_free"],
}


def _register(client: TestClient, email: str = "mehran@example.com") -> dict[str, Any]:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _auth_headers(client: TestClient, email: str = "mehran@example.com") -> dict[str, str]:
    response = client.post("/api/v1/auth/token", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_register_login_me_and_profile(client: TestClient) -> None:
    user = _register(client, "Mehran@Example.com")
    assert user["email"] == "mehran@example.com"
    assert "password" not in str(user)

    headers = _auth_headers(client, "MEHRAN@example.com")
    assert client.get("/api/v1/me", headers=headers).json()["id"] == user["id"]

    assert client.get("/api/v1/me/profile", headers=headers).status_code == 404

    saved = client.put("/api/v1/me/profile", headers=headers, json=PROFILE)
    assert saved.status_code == 200, saved.text
    assert saved.json()["weight_kg"] == 64.3  # rounded to one decimal by the domain
    assert saved.json()["dietary_preferences"] == ["dairy_free", "vegetarian"]

    updated = client.put(
        "/api/v1/me/profile", headers=headers, json=PROFILE | {"goal": "lose_weight"}
    )
    assert updated.json()["goal"] == "lose_weight"
    assert client.get("/api/v1/me/profile", headers=headers).json() == updated.json()


def test_duplicate_registration_is_409(client: TestClient) -> None:
    _register(client)
    response = client.post(
        "/api/v1/auth/register", json={"email": "MEHRAN@example.com", "password": PASSWORD}
    )
    assert response.status_code == 409
    assert response.json()["type"] == "/problems/email_already_registered"


@pytest.mark.parametrize(
    "credentials",
    [
        {"email": "mehran@example.com", "password": "wrong password!"},
        {"email": "nobody@example.com", "password": PASSWORD},
    ],
)
def test_bad_credentials_are_401_and_indistinguishable(
    client: TestClient, credentials: dict[str, str]
) -> None:
    _register(client)
    response = client.post("/api/v1/auth/token", json=credentials)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["type"] == "/problems/invalid_credentials"


@pytest.mark.parametrize(
    ("headers", "problem"),
    [
        ({}, "/problems/not_authenticated"),
        ({"Authorization": "Bearer not.a.token"}, "/problems/invalid_token"),
    ],
)
def test_protected_endpoints_require_a_valid_token(
    client: TestClient, headers: dict[str, str], problem: str
) -> None:
    for path in ("/api/v1/me", "/api/v1/me/profile"):
        response = client.get(path, headers=headers)
        assert response.status_code == 401
        assert response.json()["type"] == problem


def test_profile_validation(client: TestClient) -> None:
    _register(client)
    headers = _auth_headers(client)

    minor = client.put(
        "/api/v1/me/profile", headers=headers, json=PROFILE | {"birth_date": "2012-01-01"}
    )
    assert minor.status_code == 422
    assert minor.json()["type"] == "/problems/invalid_profile"

    bad_enum = client.put("/api/v1/me/profile", headers=headers, json=PROFILE | {"goal": "bulk"})
    assert bad_enum.status_code == 422
    assert bad_enum.json()["type"] == "/problems/request_validation_error"


def test_weak_password_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "a@example.com", "password": "short"}
    )
    assert response.status_code == 422
