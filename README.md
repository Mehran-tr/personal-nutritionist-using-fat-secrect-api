# Personal Nutritionist API

FastAPI backend for a personal-nutritionist app. Food data comes from the
[fatsecret Platform API](https://platform.fatsecret.com). Users, diaries, targets
and coaching logic are ours.

> **Status:** step 1 (skeleton) and step 2 (food catalog + fatsecret adapter) are done.
> Next up: identity & profile → targets → diary → coach.

## Quick start

```bash
cp .env.example .env          # add your fatsecret client id/secret
make install
make run                      # http://localhost:8000/docs
# or, with Redis:
make up
```

```bash
curl "localhost:8000/api/v1/foods?q=greek%20yogurt&page_size=5"
curl  localhost:8000/api/v1/foods/1641
curl  localhost:8000/api/v1/foods/barcode/4006381333931
```

`make check` runs everything CI runs: ruff, mypy `--strict`, import-linter, pytest.

## Architecture

A modular monolith. Each feature module is split into ports-and-adapters layers:

```
src/nutritionist/
├── main.py                 app factory + lifespan
├── bootstrap.py            composition root — the ONLY place adapters are chosen
├── core/                   shared kernel: config, logging, cache port, error base classes
├── api/                    cross-cutting HTTP: problem+json errors, request-id middleware, health
├── integrations/
│   └── fatsecret/          vendor client: OAuth2, retries, JSON shape models. No domain knowledge.
└── modules/
    └── catalog/
        ├── domain/         Food, Serving, Nutrients, Gtin, SearchQuery, FoodProvider port, errors
        ├── application/    use cases: SearchFoods, GetFood, LookupBarcode
        ├── infrastructure/ FatSecretFoodProvider, mapper (anti-corruption layer), cache decorator
        └── api/            router, request/response schemas, DI providers
```

Dependency rule: `api | infrastructure → application → domain`. It is **enforced**
by `import-linter` (see `[tool.importlinter]` in `pyproject.toml`), so a layer
violation fails CI.

Request flow for `GET /api/v1/foods/{id}`:

```
router → GetFood use case → FoodProvider (port)
                               └─ CachedFoodProvider (Redis, read-through)
                                    └─ FatSecretFoodProvider (errors → domain errors)
                                         └─ FatSecretClient (OAuth2, retries) → mapper → Food
```

### Key decisions

| Decision | Why |
|---|---|
| fatsecret is a *data provider*, not our system of record | We own users and diaries. That avoids vendor lock-in and 3-legged OAuth1. See `docs/adr/0001`. |
| Vendor client and mapper are separate | `integrations/fatsecret` can be reused (recipes, NLP) without leaking their JSON into our domain. |
| `Decimal` for all nutrient values | Diary totals are sums compared to targets; float drift is unacceptable. Serialized as JSON numbers. |
| Endpoint versions pinned in config | fatsecret deprecates versions regularly. Upgrades are explicit and covered by contract fixtures. |
| Barcodes validated (GS1 check digit) before any upstream call | A mistyped barcode doesn't cost API quota. |
| Cache failures degrade, never fail | If Redis goes down the API gets slower, not unavailable. |
| Errors are RFC 9457 `application/problem+json` | One error shape for clients, with `request_id` for support. |

### Error mapping

| Situation | HTTP | `type` |
|---|---|---|
| Unknown food / barcode | 404 | `/problems/food_not_found` |
| Bad barcode / search input | 422 | `/problems/invalid_barcode`, `/problems/request_validation_error` |
| fatsecret down, timing out, rate-limiting (after retries) | 503 | `/problems/food_provider_unavailable` |
| fatsecret business/shape error | 502 | `/problems/food_provider_error` |

## Testing

| Suite | What it proves |
|---|---|
| `tests/unit` | Domain rules, use cases, cache decorator, token manager, HTTP client behaviour (respx) |
| `tests/contract` | Recorded fatsecret payloads map correctly to our domain, including vendor quirks |
| `tests/e2e` | Full app: routing, middleware, error format, serialization (provider faked at the composition root) |

**Upgrading a fatsecret endpoint:** record a real response into
`tests/contract/fatsecret/fixtures/`, bump the path in `FatSecretSettings`, and
make the contract tests pass. The fixtures in this repo follow the documented
shapes. Replace them with real recordings from your account as soon as you have keys.

## fatsecret notes

- Uses **OAuth 2.0 client credentials**. Search requires the `premier` scope
  (Premier or Premier Free plans). Barcode lookup is Premier-only.
- Pinned versions: `foods.search` v6, `food.get` v6, `food.find_id_for_barcode` v1.
- Their terms require **"Powered by fatsecret"** attribution in the client UI.
  Check their terms on how long data may be cached, and set `CACHE__*_TTL_SECONDS` to match.
