# Personal Nutritionist API

FastAPI backend for a personal-nutritionist app. Food data comes from the
[fatsecret Platform API](https://platform.fatsecret.com). Users, diaries, targets
and coaching logic are ours.

> **Status:** steps 1–4 done: skeleton, food catalog + fatsecret adapter,
> identity (accounts, JWT), profile on PostgreSQL, and daily nutrition targets.
> Next up: diary → coach.

## Quick start

```bash
cp .env.example .env          # fatsecret keys + AUTH__JWT_SECRET
make install
make db                       # Postgres + Redis in Docker
make migrate                  # alembic upgrade head
make run                      # http://localhost:8000/docs
# or everything in containers (runs migrations first):
make up
```

```bash
curl -X POST localhost:8000/api/v1/auth/register -H 'content-type: application/json' \
     -d '{"email":"me@example.com","password":"correct horse battery"}'
curl -X POST localhost:8000/api/v1/auth/token -H 'content-type: application/json' \
     -d '{"email":"me@example.com","password":"correct horse battery"}'   # -> access_token
curl -X PUT localhost:8000/api/v1/me/profile -H "Authorization: Bearer $TOKEN" \
     -H 'content-type: application/json' \
     -d '{"sex":"male","birth_date":"1990-04-01","height_cm":180,"weight_kg":85,
          "activity_level":"light","goal":"lose_weight","dietary_preferences":["halal"]}'

curl "localhost:8000/api/v1/me/targets?macro_split=high_protein" -H "Authorization: Bearer $TOKEN"

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
├── db_models.py            imports every module's ORM so Alembic sees the full schema
├── core/                   shared kernel: config, logging, clock, ids, errors,
│                           cache port, DB base + UnitOfWork, AccessTokenVerifier port
├── api/                    cross-cutting HTTP: problem+json errors, request-id middleware,
│                           health, CurrentUserId dependency
├── integrations/
│   └── fatsecret/          vendor client: OAuth2, retries, JSON shape models. No domain knowledge.
└── modules/
    ├── catalog/            food search / lookup / barcode (fatsecret behind a port)
    ├── identity/           register, login (JWT), /me — Argon2id, timing-safe login
    ├── profile/            body metrics, activity, goal, dietary preferences
    └── targets/            BMR → TDEE → calorie target → macros (pure domain, no DB)
                            (each module: domain / application / [infrastructure] / api)
interop/                    cross-module adapters (e.g. profile → targets), used only by bootstrap
migrations/                 Alembic (async), one revision per schema change
```

Dependency rule: `api | infrastructure → application → domain`, and **modules
never import each other**; they share only `nutritionist.core` (e.g. `UserId`,
`AccessTokenVerifier`). Both rules are **enforced** by `import-linter` (see
`[tool.importlinter]` in `pyproject.toml`), so a violation fails CI.

When one module needs another's data, it declares a **port in its own
vocabulary** (e.g. targets' `BodyStatsProvider`). A small adapter in
`nutritionist/interop/` implements it on top of the other module's public use
cases. Import-linter makes sure only `bootstrap` uses `interop`.

Transactions belong to use cases, not to HTTP requests: each use case opens a
module-specific Unit of Work (`async with self.uow() as uow: ... await uow.commit()`),
and nothing is persisted without an explicit commit.

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
| Use-case-owned Unit of Work | Transaction boundaries are business decisions, and they are testable with an in-memory fake. |
| Argon2id in a worker thread, timing-equalised login | Strong hashing without blocking the event loop. Response times don't reveal which emails are registered. |
| Short-lived JWT access tokens, verified against an injected clock | Stateless and deterministic to test. Refresh tokens come when a client needs them (see `docs/adr/0003`). |
| Profiles for adults only (18+) | The energy equations used for targets are validated for adults. |
| Targets are computed, not stored | They are a pure function of the profile and today's date, so they can never go stale. Stored when the diary needs history. See `docs/adr/0004`. |
| Safety floors and caps, reported as `adjustments` | Users see *why* their number differs from a textbook formula, and nobody gets a crash-diet target. |
| Migrations run as a separate step, never on app start | Multiple replicas can't race on a schema change. |

### Error mapping

| Situation | HTTP | `type` |
|---|---|---|
| Missing/invalid token, bad credentials | 401 (+ `WWW-Authenticate: Bearer`) | `/problems/not_authenticated`, `/problems/invalid_token`, `/problems/invalid_credentials` |
| Email already registered | 409 | `/problems/email_already_registered` |
| Profile not created yet | 404 | `/problems/profile_not_found` |
| Profile out of range (age, height, weight) | 422 | `/problems/invalid_profile` |
| Targets requested before a profile exists | 404 | `/problems/profile_required` |
| Unknown food / barcode | 404 | `/problems/food_not_found` |
| Bad barcode / search input | 422 | `/problems/invalid_barcode`, `/problems/request_validation_error` |
| fatsecret down, timing out, rate-limiting (after retries) | 503 | `/problems/food_provider_unavailable` |
| fatsecret business/shape error | 502 | `/problems/food_provider_error` |

## Testing

| Suite | What it proves |
|---|---|
| `tests/unit` | Domain rules, use cases (in-memory UoW fakes), JWT/Argon2, cache decorator, fatsecret client (respx) |
| `tests/unit/targets` | Hand-computed reference values, plus invariants checked on a 3,240-case grid over the valid input space (floors, protein cap, macros add up to calories, nothing negative) |
| `tests/contract` | Recorded fatsecret payloads map correctly to our domain, including vendor quirks |
| `tests/integration` | Repositories and UoWs on **real PostgreSQL**; migrations match the models (`alembic check`) and downgrade cleanly |
| `tests/e2e` | Full app on a real DB: account journey, auth errors, problem+json, serialization. Only fatsecret is faked. |

DB tests use `TEST_DATABASE_URL` (default: local `nutritionist_test`). The schema is
built **by the real migrations**. Locally, DB tests are skipped if Postgres isn't
running. In CI they are required.

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
