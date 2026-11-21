"""A local stand-in for the fatsecret API, for load tests and offline development.

Serves the OAuth token endpoint plus food.get, foods.search and barcode lookup
with realistic payloads and an artificial latency (default 40 ms).

    uv run python perf/fake_fatsecret.py --port 9100 --latency-ms 40
    FATSECRET__TOKEN_URL=http://localhost:9100/connect/token \
    FATSECRET__BASE_URL=http://localhost:9100/rest make run
"""

import argparse
import asyncio
import random

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

LATENCY = 0.04


def _food(food_id: int) -> dict[str, object]:
    rnd = random.Random(food_id)
    return {
        "food_id": str(food_id),
        "food_name": f"Food {food_id}",
        "food_type": "Generic",
        "servings": {
            "serving": [
                {
                    "serving_id": f"{food_id}01",
                    "serving_description": "100 g",
                    "metric_serving_amount": "100.000",
                    "metric_serving_unit": "g",
                    "is_default": "1",
                    "calories": str(rnd.randint(40, 500)),
                    "protein": f"{rnd.uniform(0, 30):.2f}",
                    "carbohydrate": f"{rnd.uniform(0, 60):.2f}",
                    "fat": f"{rnd.uniform(0, 25):.2f}",
                    "fiber": f"{rnd.uniform(0, 8):.1f}",
                    "sodium": str(rnd.randint(0, 900)),
                }
            ]
        },
    }


async def token(_: Request) -> JSONResponse:
    await asyncio.sleep(LATENCY)
    return JSONResponse({"access_token": "fake", "expires_in": 86400, "token_type": "Bearer"})


async def food_get(request: Request) -> JSONResponse:
    await asyncio.sleep(LATENCY)
    return JSONResponse({"food": _food(int(request.query_params["food_id"]))})


async def search(request: Request) -> JSONResponse:
    await asyncio.sleep(LATENCY)
    size = int(request.query_params.get("max_results", 20))
    base = abs(hash(request.query_params["search_expression"])) % 10_000
    return JSONResponse(
        {
            "foods_search": {
                "max_results": str(size),
                "total_results": "200",
                "page_number": request.query_params.get("page_number", "0"),
                "results": {"food": [_food(base + i) for i in range(size)]},
            }
        }
    )


async def barcode(request: Request) -> JSONResponse:
    await asyncio.sleep(LATENCY)
    return JSONResponse({"food_id": {"value": str(int(request.query_params["barcode"]) % 1000)}})


app = Starlette(
    routes=[
        Route("/connect/token", token, methods=["POST"]),
        Route("/rest/food/v6", food_get),
        Route("/rest/foods/search/v6", search),
        Route("/rest/food/barcode/find-by-id/v1", barcode),
    ]
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--latency-ms", type=int, default=40)
    args = parser.parse_args()
    LATENCY = args.latency_ms / 1000
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
