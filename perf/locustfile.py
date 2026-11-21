"""Load test: a realistic daily-use mix for logged-in users.

make perf-up        # fake fatsecret + API (rate limiting off, local only)
make loadtest       # 50 users for 60 s, CSV results in perf/results/
"""

import json
import os
import random
import uuid
from datetime import date, timedelta
from pathlib import Path

from locust import HttpUser, between, task

PASSWORD = "correct horse battery"
TODAY = date.today()
TOKENS_FILE = Path("perf/results/tokens.json")
# MODE=steady: reuse pre-seeded users (perf/seed_users.py) -> measures daily use only.
# MODE=mixed (default): every simulated user registers -> includes login storms.
MODE = os.environ.get("MODE", "mixed")
_tokens = json.loads(TOKENS_FILE.read_text()) if MODE == "steady" else []


class DailyUser(HttpUser):
    wait_time = between(0.2, 1.0)

    def on_start(self) -> None:
        if _tokens:
            self.client.headers["Authorization"] = f"Bearer {_tokens.pop()}"
            return
        creds = {"email": f"load-{uuid.uuid4().hex}@example.com", "password": PASSWORD}
        self.client.post("/api/v1/auth/register", json=creds)
        token = self.client.post("/api/v1/auth/token", json=creds).json()["access_token"]
        self.client.headers["Authorization"] = f"Bearer {token}"
        self.client.put(
            "/api/v1/me/profile",
            json={
                "sex": random.choice(["female", "male"]),
                "birth_date": "1990-05-05",
                "height_cm": random.randint(155, 195),
                "weight_kg": random.randint(55, 110),
                "activity_level": "moderate",
                "goal": random.choice(["lose_weight", "maintain", "gain_weight"]),
            },
        )
        for _ in range(4):
            self.log_food()

    def _day(self) -> str:
        return (TODAY - timedelta(days=random.choice([0, 0, 0, 1]))).isoformat()

    @task(6)
    def diary_day(self) -> None:
        self.client.get(f"/api/v1/me/diary/{self._day()}", name="/me/diary/{day}")

    @task(3)
    def targets(self) -> None:
        self.client.get("/api/v1/me/targets")

    @task(2)
    def coach(self) -> None:
        self.client.get(f"/api/v1/me/coach/{self._day()}", name="/me/coach/{day}")

    @task(2)
    def log_food(self) -> None:
        food_id = random.randint(1, 300)  # popular foods repeat: exercises the cache
        self.client.post(
            "/api/v1/me/diary/entries",
            json={
                "day": TODAY.isoformat(),
                "meal": random.choice(["breakfast", "lunch", "dinner", "snack"]),
                "food_id": str(food_id),
                "serving_id": f"{food_id}01",
                "servings": random.choice([0.5, 1, 1.5, 2]),
            },
            name="/me/diary/entries",
        )

    @task(2)
    def search(self) -> None:
        q = random.choice(["apple", "chicken", "rice", "yogurt", "oats", "salmon", "bread"])
        self.client.get(f"/api/v1/foods?q={q}&page_size=10", name="/foods?q")

    @task(1)
    def food(self) -> None:
        self.client.get(f"/api/v1/foods/{random.randint(1, 300)}", name="/foods/{id}")
