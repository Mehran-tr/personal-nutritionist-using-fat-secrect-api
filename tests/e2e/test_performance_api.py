import gzip
from datetime import date

from fastapi.testclient import TestClient

TODAY = date.today().isoformat()


def test_large_responses_are_gzipped_small_ones_are_not(authed_client: TestClient) -> None:
    big = authed_client.get("/api/v1/me/diary/" + TODAY, headers={"accept-encoding": "gzip"})
    # Seed some data so the body is above the 1 KiB threshold.
    authed_client.post(
        "/api/v1/me/diary/entries/batch",
        json={
            "day": TODAY,
            "meal": "lunch",
            "items": [{"food_id": "1", "serving_id": "1-100g"}] * 5,
        },
    ).raise_for_status()
    big = authed_client.get(f"/api/v1/me/diary/{TODAY}", headers={"accept-encoding": "gzip"})
    small = authed_client.get("/health/live", headers={"accept-encoding": "gzip"})

    assert big.headers["content-encoding"] == "gzip"
    assert big.json()["totals"]["calories_kcal"] == 260.0  # httpx decompresses transparently
    assert "content-encoding" not in small.headers
    assert big.headers["x-content-type-options"] == "nosniff"  # headers survive compression
    assert len(gzip.compress(big.content)) < len(big.content)


def test_etag_revalidation_returns_304_until_data_changes(authed_client: TestClient) -> None:
    url = f"/api/v1/me/diary/{TODAY}"
    first = authed_client.get(url)
    etag = first.headers["etag"]
    assert etag.startswith('W/"')

    unchanged = authed_client.get(url, headers={"if-none-match": etag})
    assert unchanged.status_code == 304
    assert unchanged.content == b""
    assert unchanged.headers["etag"] == etag

    authed_client.post(
        "/api/v1/me/diary/entries",
        json={"day": TODAY, "meal": "snack", "food_id": "1", "serving_id": "1-100g"},
    ).raise_for_status()
    changed = authed_client.get(url, headers={"if-none-match": etag})
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag


def test_food_data_is_cacheable_by_the_client_only(authed_client: TestClient) -> None:
    food = authed_client.get("/api/v1/foods/1")
    assert food.headers["cache-control"] == "private, max-age=3600"
    search = authed_client.get("/api/v1/foods", params={"q": "apple"})
    assert search.headers["cache-control"] == "private, max-age=300"
    assert authed_client.get("/api/v1/me").headers["cache-control"] == "no-store"


def test_batch_meal_logging(authed_client: TestClient) -> None:
    response = authed_client.post(
        "/api/v1/me/diary/entries/batch",
        json={
            "day": TODAY,
            "meal": "dinner",
            "items": [
                {"food_id": "1", "serving_id": "1-100g", "servings": 2},
                {"food_id": "2", "serving_id": "2-100g"},
            ],
        },
    )
    assert response.status_code == 201
    assert [e["food"]["name"] for e in response.json()] == ["Apple", "Apple pie"]

    too_many = authed_client.post(
        "/api/v1/me/diary/entries/batch",
        json={
            "day": TODAY,
            "meal": "dinner",
            "items": [{"food_id": "1", "serving_id": "1-100g"}] * 21,
        },
    )
    assert too_many.status_code == 422

    partial = authed_client.post(
        "/api/v1/me/diary/entries/batch",
        json={
            "day": TODAY,
            "meal": "dinner",
            "items": [
                {"food_id": "1", "serving_id": "1-100g"},
                {"food_id": "999", "serving_id": "x"},
            ],
        },
    )
    assert partial.status_code == 404
    day = authed_client.get(f"/api/v1/me/diary/{TODAY}").json()
    assert len(day["entries"]) == 2  # the failed batch wrote nothing


def test_metrics_are_internal_and_use_route_templates(authed_client: TestClient) -> None:
    authed_client.get(f"/api/v1/me/diary/{TODAY}")
    body = authed_client.get("/metrics").text  # test client is on a private IP

    assert 'http_requests_total{method="GET",route="/api/v1/me/diary/{day}",status="200"}' in body
    assert TODAY not in body  # raw paths never become labels
    assert "db_query_duration_seconds_count" in body


def test_coach_reports_summary_pending_flag(authed_client: TestClient) -> None:
    review = authed_client.get(f"/api/v1/me/coach/{TODAY}").json()
    assert review["summary_pending"] is False  # LLM disabled in tests
