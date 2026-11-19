from datetime import date, timedelta

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery"
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()


def _headers(client: TestClient) -> dict[str, str]:
    creds = {"email": "c@example.com", "password": PASSWORD}
    assert client.post("/api/v1/auth/register", json=creds).status_code == 201
    token = client.post("/api/v1/auth/token", json=creds).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_review_of_a_logged_day(client: TestClient) -> None:
    headers = _headers(client)
    client.put(
        "/api/v1/me/profile",
        headers=headers,
        json={
            "sex": "female",
            "birth_date": "1992-03-03",
            "height_cm": 168,
            "weight_kg": 62,
            "activity_level": "light",
            "goal": "maintain",
        },
    ).raise_for_status()
    # A day of apple pie only: far too much energy, very little protein.
    client.post(
        "/api/v1/me/diary/entries",
        headers=headers,
        json={
            "day": YESTERDAY,
            "meal": "dinner",
            "food_id": "2",
            "serving_id": "2-100g",
            "servings": 12,
        },
    ).raise_for_status()

    review = client.get(f"/api/v1/me/coach/{YESTERDAY}", headers=headers)

    assert review.status_code == 200, review.text
    body = review.json()
    assert body["status"] == "complete"
    assert body["summary"] is None  # LLM phrasing is off by default
    first = body["insights"][0]
    assert (first["code"], first["severity"], first["unit"]) == ("calories_over", "warning", "kcal")
    assert first["actual"] == 2844.0  # 12 x 237
    assert "protein_under" in [i["code"] for i in body["insights"]]


def test_empty_today_and_auth(client: TestClient) -> None:
    headers = _headers(client)
    today = client.get(f"/api/v1/me/coach/{date.today().isoformat()}", headers=headers).json()
    assert today["status"] == "in_progress"
    assert [i["code"] for i in today["insights"]] == ["nothing_logged"]
    assert client.get(f"/api/v1/me/coach/{YESTERDAY}").status_code == 401
