# Performance checklist

Every item of the API performance checklist, with where it is handled and how
it is verified, plus **measured results** from load tests.

**Legend**
- ✅ in place (and tested)
- 🛠️ added in the performance pass (tested)
- 🏗️ deployment/infrastructure (config provided)
- ➖ not applicable, with the reason

## Measured results

`perf/run_loadtest.sh` runs Locust against a live uvicorn worker, with real
Postgres + Redis and a local fake fatsecret (40 ms latency). The mix: diary day
6, targets 3, coach 2, log food 2, search 2, food 1. Everything ran on one 2-CPU
machine, load generator included, so absolute numbers are conservative.

| Scenario (1 worker, 2 CPUs) | Requests | Failures | p50 | p95 | p99 | Log food p95 |
|---|---|---|---|---|---|---|
| Before: 50 users incl. sign-ups | 4,426 | 0 | 6 ms | 600 ms | 2,300 ms | 1,100 ms |
| After, hashing on the default thread pool (6 threads) | 4,444 | 0 | 6 ms | 450 ms | 2,500 ms | 1,200 ms |
| **After, bounded hashing pool** | 4,620 | 0 | 6 ms | **64 ms** | 2,700 ms¹ | **74 ms** |
| **Steady state**: 50 users, daily use | 4,691 | 0 | 6 ms | **48 ms** | **60 ms** | 60 ms |
| **Stress**: 200 users, daily use | 15,272 | 0 | 37 ms | 160 ms | 260 ms | 220 ms |

¹ p99 is the sign-up/login requests themselves. 100 Argon2 hashes on 2 CPUs
queue for a few seconds by design. They no longer stall everything else.

**Biggest finding:** a login burst ran Argon2 on the default executor
(`cpu_count + 4` threads), took every core and **starved the event loop**. Every
unrelated request waited, and primary-key lookups showed up as 400 ms "slow
queries". Hashing now runs on a dedicated pool of `cpu_count − 1` threads, which
cut overall p95 7× and log-food p95 15×. The other changes below matter more
at higher scale than this test exercises.

**Capacity:** about **250 req/s per worker at p95 160 ms** on this hardware. Scale out
with replicas (see Load balancing).

Reproduce: `make loadtest` (mixed) or `MODE=steady make loadtest users=200`.

## Optimize API response

| Item | Status | Where / how |
|---|---|---|
| Payload size limits | ✅ | Requests ≤ 64 KiB (`413`). Responses are bounded: search ≤ 50 items/page, ≤ 200 diary entries/day (🛠️ `max_entries_per_day`), batches ≤ 20 items. |
| Response compression | 🛠️ | `GZipMiddleware` for bodies ≥ 1 KiB (smaller isn't worth the CPU), plus zstd/gzip at Caddy. Security headers survive compression (tested). |
| Efficient pagination | ✅ | Catalog: `page`/`page_size` (max 50) passed through to fatsecret. Diary: naturally paged by day, with an index on `(user_id, day)`. |
| Minimize server work | 🛠️ | Day targets were recomputed on **every** food log. They're now computed once per user per day (tested). Coach LLM phrasing moved off the request path. ETag/304 skips re-sending unchanged bodies. |

## Asynchronism

| Item | Status | Where / how |
|---|---|---|
| Offload heavy tasks | 🛠️ | LLM phrasing (1–3 s) runs in `BackgroundRunner` (bounded, deduplicated per key). The API answers immediately with `summary_pending: true`, and the next request is a cache hit. Argon2 runs on its own bounded thread pool. |
| Message brokers between services | ➖/🏗️ | One deployable (modular monolith): modules talk in-process via `interop/`, with no network hops. Background work today is best-effort and cache-backed, so losing it is harmless. **When durable jobs appear** (emails, exports), use arq/Celery on Redis. When a module is split into a service, publish events via a transactional outbox to a broker (Redis Streams/RabbitMQ). |

## Load balancing & scaling

| Item | Status | Where / how |
|---|---|---|
| Horizontal / vertical scaling | ✅/🏗️ | The app is **stateless** (JWT, limiter and caches in Redis, data in Postgres), so it scales horizontally: `docker compose up --scale api=3`. One worker per container (clean metrics, graceful shutdown). Container resource limits are set. |
| Load balancing | 🏗️ | Caddy: dynamic upstreams for all replicas, `least_conn`, active health checks on `/health/live`, passive ejection, retries, keep-alive to upstreams. |

## Code optimization

| Item | Status | Where / how |
|---|---|---|
| Streaming large requests/responses | ➖ | No large payloads (bounded above). ETag buffering falls back to streaming above 1 MiB. |
| Profile to find bottlenecks | 🛠️ | Load tests + `/metrics` + slow-query log found the event-loop starvation above. Postgres: `pg_stat_statements` enabled in compose. |
| Algorithms & data structures | ✅ | Hot paths are O(entries per day), with entries capped at 200. Targets are pure arithmetic. Decimal only where money-like precision matters. |
| Critical paths | 🛠️ | Log food: concurrent cached lookups → targets only when missing → one short transaction. No nested DB connections, which avoids a pool-exhaustion deadlock under load. |
| Compiled languages (Go/Rust) | ➖ | The CPU-heavy parts are already native: Argon2 (C), pydantic-core (Rust) for validation/serialization, asyncpg (C). Profiling shows no Python hotspot worth a rewrite. |
| Architecture (SOA/microservices) | ✅ | Modular monolith with **enforced** module boundaries (import-linter). Any module can be extracted later; until a module needs independent scaling, extra network hops would only add latency. |
| Timeouts & efficient retries | 🛠️ | fatsecret: 2 s connect / 5 s per attempt, 3 attempts, exponential backoff with full jitter, only for transient errors. Anthropic: 8 s, no retry (optional feature). Postgres: connect 5 s, pool wait 10 s, `statement_timeout` 5 s, idle-in-transaction 10 s, recycle 30 min. Redis: 0.5 s and fail open. |
| Batch similar requests | 🛠️ | `POST /me/diary/entries/batch`: log a meal in one round trip and one transaction (all-or-nothing). Concurrent identical cache misses are **coalesced** into one upstream call (single-flight, tested with 25 concurrent requests → 1 call). |

## Monitoring and logging

| Item | Status | Where / how |
|---|---|---|
| Comprehensive monitoring | 🛠️ | `/metrics` (internal networks only): HTTP rate/latency per route **template**, DB query latency + slow-query count, upstream latency per service/outcome, cache hit/miss/coalesced, background task outcomes. |
| Prometheus, Grafana, ELK | 🏗️ | `docker compose --profile observability up` → Prometheus (discovers every replica) + Grafana. JSON logs on stdout, ready for ELK/Loki. |
| Asynchronous logging | 🛠️ | `QueueWriter`: the request thread only enqueues. A background thread writes to stdout. If the queue is full, lines are dropped instead of blocking requests. |

## Performance testing

| Item | Status | Where / how |
|---|---|---|
| Regular performance testing | 🛠️ | `perf/`: Locust scenario, fake fatsecret, user seeding, `run_loadtest.sh` with mixed and steady modes. CSV results go to `perf/results/`. **Next:** run it nightly in CI against a staging stack and fail on p95 regressions. |

## Caching

| Item | Status | Where / how |
|---|---|---|
| HTTP / client / CDN caching | 🛠️ | Food data: `Cache-Control: private, max-age=3600` (search: 300 s). Per-user data: `no-store`. Every GET has a weak **ETag**, and `If-None-Match` → `304`. CDN ➖: all responses are authenticated and per-user. |
| Cache patterns | ✅ | Read-through (cache-aside) for fatsecret data in Redis, with single-flight. Coach phrasing is cached by content hash. |
| Invalidation | ✅ | TTLs for upstream data, a schema-version prefix in keys (bump to invalidate everything), content-addressed phrasing keys (nothing to invalidate). Diary data is never cached server-side, so it's never stale. ETags are computed from the actual body, so they're always correct. |

## Databases

| Item | Status | Where / how |
|---|---|---|
| Connection pooling | ✅ | SQLAlchemy async pool + asyncpg, `pool_pre_ping`. |
| Pool tuning | 🛠️ | `pool_size`, `max_overflow`, `pool_timeout`, 🛠️ `pool_recycle`. Rule: replicas × (pool_size + max_overflow) < `max_connections` (200 in compose). Above that, put PgBouncer in front. |
| Efficient indexes | ✅ | `(user_id, day)` on diary entries. PKs on all lookups, unique email. 🛠️ An `EXPLAIN` test proves the diary query can use the index. |
| ORM queries | ✅ | Explicit columns, PK `get`s, one query per need. 🛠️ Statement timing on every query. |
| Lazy / eager loading, batching | ✅ | No ORM relationships, so no N+1 is possible. The batch insert for meals is one transaction. |
| Pagination | ✅ | See above. |
| No `SELECT *` | ✅ | SQLAlchemy selects named columns only. The `EXPLAIN` in tests is the only `*`. |
| Denormalize for reads | ✅ | Diary entries embed a snapshot of the food and nutrients, and day targets are snapshotted. Reading a day needs no joins and no API calls. |
| Avoid unnecessary JOINs | ✅ | Hot paths have no joins. |
| Maintenance (vacuum, cleanup) | 🏗️ | Postgres autovacuum (default on). Review `pg_stat_user_tables` for bloat. Data retention: user data is deleted with the account (FK cascades). |
| Slow-query logging | 🛠️ | App: `slow_query` log + counter (≥ 200 ms, no parameters logged). Postgres: `log_min_duration_statement=250`. Note: the app timer includes event-loop lag, so compare with Postgres' own log. |
| Replication | 🏗️ | Use a managed Postgres with a standby replica for failover. Read replicas aren't needed yet: the read paths take single-digit ms on the primary. |
| Sharding | ➖ | Not needed at this scale. If it ever is, `user_id` is the natural shard key: every query is scoped to one user. |
| Database profiling tools | 🛠️ | `pg_stat_statements` preloaded in compose (`docker/postgres-init.sql`), plus `EXPLAIN (ANALYZE, BUFFERS)` for single queries. |

## Security (performance list)

| Item | Status | Where / how |
|---|---|---|
| Dependencies up to date | 🛠️ | Dependabot (uv, Docker, Actions), weekly and grouped. CI runs `pip-audit` on the lock file. Current result: **no known vulnerabilities**. |
| Authn/authz, rate limiting, audits | ✅ | See SECURITY.md. |

## Network

| Item | Status | Where / how |
|---|---|---|
| Host close to users | 🏗️ | Deploy in the region of your users (e.g. EU-Central for Germany). Keep Postgres, Redis and the API in the same zone: the hot path makes several DB/Redis round trips. |
| HTTP keep-alive | 🛠️ | Clients ↔ Caddy, Caddy ↔ API (uvicorn keep-alive 75 s > proxy idle 60 s, which avoids stale-socket 502s), API ↔ fatsecret/Anthropic (one shared, pooled httpx client). |
| CDN for static assets | ➖ | The API serves no static assets. Clients should put theirs on a CDN. |
| Prefetch / preload | 🛠️ | Startup warm-up: DB pool connection, Redis, fatsecret OAuth token, so the first users don't pay for handshakes. Never fails startup. |

## Known trade-offs

- **Background phrasing is in-process:** a deploy can drop a running task. That's harmless,
  because the next request re-schedules it. Don't put non-idempotent work there.
- **Coalescing is per process:** across replicas, each replica can make one upstream
  call per key during a miss window. That's fine at this scale. A Redis lock would be the
  next step if fatsecret quota becomes tight.
- **Login latency under bursts is CPU-bound by design** (Argon2). Capacity is roughly
  (cores − 1) × 20 logins/s per container. The auth rate limit keeps queues short.
