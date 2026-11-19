from fastapi.testclient import TestClient

PASSWORD = "correct horse battery"


def _headers(client: TestClient) -> dict[str, str]:
    creds = {"email": "t@example.com", "password": PASSWORD}
    assert client.post("/api/v1/auth/register", json=creds).status_code == 201
    token = client.post("/api/v1/auth/token", json=creds).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_targets_follow_the_profile(client: TestClient) -> None:
    headers = _headers(client)

    missing = client.get("/api/v1/me/targets", headers=headers)
    assert missing.status_code == 404
    assert missing.json()["type"] == "/problems/profile_required"

    client.put(
        "/api/v1/me/profile",
        headers=headers,
        json={
            "sex": "male",
            "birth_date": "1990-01-01",
            "height_cm": 180,
            "weight_kg": 80,
            "activity_level": "moderate",
            "goal": "lose_weight",
        },
    ).raise_for_status()

    body = client.get("/api/v1/me/targets", headers=headers).json()
    assert body["macro_split"] == "balanced"
    assert body["calories_kcal"] > 1500
    assert set(body["macros"]) == {"protein_g", "carbohydrate_g", "fat_g", "fiber_g"}
    assert "not medical advice" in body["disclaimer"]

    low_carb = client.get(
        "/api/v1/me/targets", headers=headers, params={"macro_split": "low_carb"}
    ).json()
    assert low_carb["macros"]["carbohydrate_g"] < body["macros"]["carbohydrate_g"]
    assert low_carb["calories_kcal"] == body["calories_kcal"]


def test_unknown_split_is_422(client: TestClient) -> None:
    response = client.get(
        "/api/v1/me/targets", headers=_headers(client), params={"macro_split": "keto"}
    )
    assert response.status_code == 422


def test_targets_require_auth(client: TestClient) -> None:
    assert client.get("/api/v1/me/targets").status_code == 401
