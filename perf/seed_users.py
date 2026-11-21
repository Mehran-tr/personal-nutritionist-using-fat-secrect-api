"""Create load-test users up front, so the measured run isn't dominated by
registration hashing. Writes perf/results/tokens.json (tokens live 30 min).

    uv run python perf/seed_users.py --base http://localhost:8090 --users 50
"""

import argparse
import asyncio
import json
import random
import uuid
from pathlib import Path

import httpx

PASSWORD = "correct horse battery"


async def make_user(client: httpx.AsyncClient, gate: asyncio.Semaphore) -> str:
    async with gate:
        creds = {"email": f"seed-{uuid.uuid4().hex}@example.com", "password": PASSWORD}
        (await client.post("/api/v1/auth/register", json=creds)).raise_for_status()
        token = (await client.post("/api/v1/auth/token", json=creds)).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        (
            await client.put(
                "/api/v1/me/profile",
                headers=headers,
                json={
                    "sex": random.choice(["female", "male"]),
                    "birth_date": "1990-05-05",
                    "height_cm": random.randint(155, 195),
                    "weight_kg": random.randint(55, 110),
                    "activity_level": "moderate",
                    "goal": "maintain",
                },
            )
        ).raise_for_status()
        return token


async def seed(base: str, users: int) -> list[str]:
    gate = asyncio.Semaphore(4)
    async with httpx.AsyncClient(base_url=base, timeout=60) as client:
        return await asyncio.gather(*(make_user(client, gate) for _ in range(users)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8090")
    parser.add_argument("--users", type=int, default=50)
    args = parser.parse_args()
    tokens = asyncio.run(seed(args.base, args.users))
    Path("perf/results/tokens.json").write_text(json.dumps(tokens))
    print(f"seeded {len(tokens)} users")
