"""The daily-logging journey through the real app and database (fatsecret faked)."""

from datetime import date, timedelta
from typing import Any

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery"
TODAY = date.today().isoformat()
PROFILE: dict[str, Any] = {
    "sex": "male",
    "birth_date": "1990-01-01",
    "height_cm": 180,
    "weight_kg": 80,
    "activity_level": "moderate",
    "goal": "maintain",
    "macro_preference": "high_protein",
}


def _headers(client: TestClient, email: str = "d@example.com") -> dict[str, str]:
    creds = {"email": email, "password": PASSWORD}
    assert client.post("/api/v1/auth/register", json=creds).status_code == 201
    token = client.post("/api/v1/auth/token", json=creds).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _log(client: TestClient, headers: dict[str, str], **overrides: Any) -> Any:
    body = {"day": TODAY, "meal": "breakfast", "food_id": "1", "serving_id": "1-100g"} | overrides
    return client.post("/api/v1/me/diary/entries", headers=headers, json=body)


def test_logging_journey(client: TestClient) -> None:
    headers = _headers(client)
    client.put("/api/v1/me/profile", headers=headers, json=PROFILE).raise_for_status()

    # Saved preference flows into targets.
    targets = client.get("/api/v1/me/targets", headers=headers).json()
    assert targets["macro_split"] == "high_protein"

    apple = _log(client, headers, servings=2)
    assert apple.status_code == 201, apple.text
    assert apple.json()["nutrients"]["calories_kcal"] == 104.0  # 2 x 52, looked up server-side
    pie = _log(client, headers, food_id="2", serving_id="2-100g", meal="dinner").json()

    day = client.get(f"/api/v1/me/diary/{TODAY}", headers=headers).json()
    assert day["targets_source"] == "snapshot"
    assert day["targets"]["calories_kcal"] == targets["calories_kcal"]
    assert day["targets"]["macro_split"] == "high_protein"
    assert day["totals"]["calories_kcal"] == 341.0  # 104 + 237
    assert day["by_meal"]["dinner"]["calories_kcal"] == 237.0
    assert day["remaining"]["calories_kcal"] == targets["calories_kcal"] - 341
    assert [e["meal"] for e in day["entries"]] == ["breakfast", "dinner"]

    patched = client.patch(
        f"/api/v1/me/diary/entries/{pie['id']}", headers=headers, json={"servings": 0.5}
    )
    assert patched.json()["nutrients"]["calories_kcal"] == 118.5
    deleted = client.delete(f"/api/v1/me/diary/entries/{pie['id']}", headers=headers)
    assert deleted.status_code == 204
    day = client.get(f"/api/v1/me/diary/{TODAY}", headers=headers).json()
    assert day["totals"]["calories_kcal"] == 104.0


def test_day_targets_are_frozen_once_logging_starts(client: TestClient) -> None:
    headers = _headers(client)
    client.put("/api/v1/me/profile", headers=headers, json=PROFILE).raise_for_status()
    _log(client, headers).raise_for_status()
    before = client.get(f"/api/v1/me/diary/{TODAY}", headers=headers).json()["targets"]

    client.put(
        "/api/v1/me/profile", headers=headers, json=PROFILE | {"goal": "lose_weight"}
    ).raise_for_status()

    after = client.get(f"/api/v1/me/diary/{TODAY}", headers=headers).json()
    assert after["targets"] == before  # today's history did not move
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    future = client.get(f"/api/v1/me/diary/{tomorrow}", headers=headers).json()
    assert future["targets_source"] == "current"
    assert future["targets"]["calories_kcal"] < before["calories_kcal"]


def test_logging_before_a_profile_exists(client: TestClient) -> None:
    headers = _headers(client)
    assert _log(client, headers).status_code == 201
    day = client.get(f"/api/v1/me/diary/{TODAY}", headers=headers).json()
    assert (day["targets"], day["remaining"]) == (None, None)
    assert day["totals"]["calories_kcal"] == 52.0


def test_entries_are_private(client: TestClient) -> None:
    owner = _headers(client, "owner@example.com")
    intruder = _headers(client, "intruder@example.com")
    entry_id = _log(client, owner).json()["id"]

    for response in (
        client.patch(
            f"/api/v1/me/diary/entries/{entry_id}", headers=intruder, json={"servings": 9}
        ),
        client.delete(f"/api/v1/me/diary/entries/{entry_id}", headers=intruder),
    ):
        assert response.status_code == 404
        assert response.json()["type"] == "/problems/diary_entry_not_found"
    assert client.get(f"/api/v1/me/diary/{TODAY}", headers=intruder).json()["entries"] == []


def test_validation(client: TestClient) -> None:
    headers = _headers(client)
    far_future = (date.today() + timedelta(days=5)).isoformat()

    assert _log(client, headers, day=far_future).json()["type"] == "/problems/invalid_diary_entry"
    assert _log(client, headers, servings=0).status_code == 422
    assert (
        _log(client, headers, food_id="999").json()["type"] == "/problems/food_or_serving_not_found"
    )
    assert _log(client, headers, serving_id="nope").status_code == 404
    empty_patch = client.patch(
        "/api/v1/me/diary/entries/00000000-0000-0000-0000-000000000000", headers=headers, json={}
    )
    assert empty_patch.status_code == 422
    assert client.get("/api/v1/me/diary/not-a-date", headers=headers).status_code == 422
    assert client.get(f"/api/v1/me/diary/{TODAY}").status_code == 401
