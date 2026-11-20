# Security checklist

Every item of the API security checklist, with where it is handled and how it
is verified. Most items are enforced by tests (`tests/e2e/test_security.py` runs
them against the real app), so a regression fails CI.

**Legend**
- ✅ in place and tested
- 🛠️ added in the security pass (also tested)
- 🏗️ deployment/infrastructure (config provided here, you must apply it)
- ➖ not applicable, with the reason

## Authentication

| Item | Status | Where / how |
|---|---|---|
| Avoid Basic Auth, use a standard (JWT) | ✅ | Bearer JWT only (`api/security.py`). The only Basic auth is our *outgoing* OAuth2 client-credentials call to fatsecret, which the OAuth2 spec requires. |
| Don't reinvent auth mechanisms | ✅ | PyJWT for tokens, argon2-cffi (Argon2id) for passwords. No custom crypto. |
| Max retry + jail on login | 🛠️ | `LoginGuard`: 5 failures per account+IP → that IP is locked out of that account for 15 min. 20 failures per account across all IPs → account locked for 1 h. Rejected before any hashing, `429` + `Retry-After`. Per-IP lockout means an attacker can't lock the real owner out. Emails are stored only as hashes in Redis. |
| Encrypt sensitive data | ✅/🏗️ | Passwords: Argon2id. Secrets: `SecretStr` (never logged or printed). In transit: TLS at the proxy (`docker/Caddyfile`). **To do at deploy:** DB TLS (`?ssl=require` in `DATABASE__URL`), encrypted DB volumes/backups (managed Postgres does this by default). |

## Access control

| Item | Status | Where / how |
|---|---|---|
| Throttling (DDoS / brute force) | 🛠️ | `RateLimitMiddleware`: per client IP, 300 req/min overall, 10 req/min on `/auth/*`, `429` + `Retry-After`. Redis-backed, so limits are shared across replicas. Real volumetric DDoS must still be absorbed upstream (CDN/WAF, see Monitoring). |
| HTTPS + secure ciphers | 🏗️ | `docker/Caddyfile`: automatic certificates, HTTP→HTTPS redirect, TLS 1.2/1.3 with modern AEAD ciphers only. `docker compose --profile tls up`. |
| HSTS against SSL stripping | 🛠️ | `Strict-Transport-Security: max-age=63072000; includeSubDomains` when `SECURITY__HSTS_ENABLED=true`. Production refuses to start without it. |
| Directory listings off | ✅ | No static file serving at all (no `StaticFiles` mounts). `/docs` and `/openapi.json` are disabled in production and blocked at the proxy. |
| Private APIs only from safe-listed IPs | 🛠️ | `/health/ready` (reveals DB/cache state) only answers `SECURITY__INTERNAL_NETWORKS` (private ranges by default). Others get `404`. The proxy also blocks it publicly. |
| Host header validation | 🛠️ | `TrustedHostMiddleware` (`SECURITY__ALLOWED_HOSTS`). Wildcard is refused in production. |

## JWT

| Item | Status | Where / how |
|---|---|---|
| Strong secret | 🛠️ | ≥ 32 chars **and** ≥ 12 distinct characters (rejects `aaaa…`). Generate with `secrets.token_urlsafe(48)`. |
| Algorithm from backend, not header | ✅ | `algorithms=[configured]` pinned on decode. `alg: none` and other-key tokens are rejected (tested). |
| Short TTL | ✅ | 30 min access tokens, expiry checked against our clock. There are no refresh tokens yet, so there's nothing long-lived to steal (`docs/adr/0003`). |
| No sensitive data in payload | ✅ | Claims are exactly `sub` (random UUID), `iss`, `aud`, `iat`, `exp`, `jti`. No email or profile data (tested). |
| Small payload | ✅ | Six short claims (~250 bytes). |

## OAuth

| Item | Status | Reason |
|---|---|---|
| Validate `redirect_uri`, no `response_type=token`, `state` against CSRF, scopes | ➖ | This API is not an OAuth authorization server and has no OAuth login flow. Its only OAuth use is server-to-server **client credentials** to fatsecret (no redirects, browser or `state`), with a minimal, configured scope (`FATSECRET__SCOPES`). If "Sign in with Google/Apple" is added later, use a maintained library (Authlib) with PKCE + `state` and an exact-match redirect allow-list. |

## Processing

| Item | Status | Where / how |
|---|---|---|
| All endpoints behind authentication | 🛠️ | `/foods*` **were public** (anyone could spend the paid fatsecret quota) and now require a token. Only `/health/live`, `/health/ready` (internal-only), `/auth/register` and `/auth/token` are public. A test walks the whole OpenAPI spec and asserts `401` on every other operation. |
| No personal IDs in URLs | ✅ | User-scoped routes are `/me/...`. The user comes from the token, never the URL (tested via the OpenAPI spec). |
| UUIDs over auto-increment | ✅ | Users and diary entries use UUID primary keys. No sequential IDs anywhere. Other users' entries answer `404`, not `403`. |
| XML entity parsing / expansion (XXE) | ➖ | No XML or YAML is parsed anywhere. fatsecret is called with `format=json`. |
| CDN for file uploads | ➖ | No file uploads. If meal photos are added: direct-to-object-storage presigned uploads, served via CDN from a separate domain. |
| Avoid HTTP blocking on large data | ✅/🛠️ | Fully async I/O. Argon2 runs in a worker thread. Results are paginated (max 50). 🛠️ Request bodies are capped at 64 KiB (`413`, also for streamed bodies). |
| Debug mode off in production | ✅/🛠️ | `debug=False` always. Unhandled errors return a generic 500. `/docs` is off in production. 🛠️ Production refuses to start with unsafe settings (wildcard hosts, no HSTS, throttling off, in-memory limiter, non-JSON logs). |
| Non-executable stacks | 🏗️ | Container: non-root user, `read_only`, `no-new-privileges`, `cap_drop: ALL` (`compose.yml`). Python 3.13 slim images are built with NX/PIE by the distro. |

## Input

The checklist's "Input" items repeat the Access-control ones (see above). Additionally:

| Item | Status | Where / how |
|---|---|---|
| Validate all input | ✅ | Pydantic models with bounds on every field (lengths, ranges, patterns, enums), plus domain validation (age, servings, day window, GTIN check digit). |
| Proper HTTP methods | ✅ | `GET` reads, `POST` creates, `PUT` replaces, `PATCH` updates, `DELETE` removes. Others → `405`. |
| No secrets in URLs | ✅ | Credentials only in JSON bodies, tokens only in the `Authorization` header. |

## Output

| Item | Status | Where / how |
|---|---|---|
| `X-Content-Type-Options: nosniff` | 🛠️ | `SecurityHeadersMiddleware`, on every response including 4xx/5xx/429. |
| `X-Frame-Options: DENY` | 🛠️ | Same middleware. |
| `Content-Security-Policy: default-src 'none'` | 🛠️ | `default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'`. Swagger `/docs` (non-production only) gets the minimal policy it needs. |
| Remove fingerprinting headers | 🛠️ | `uvicorn --no-server-header`. The middleware strips `server`/`x-powered-by`. Caddy drops its own `Server` header. |
| Force content type | ✅ | `application/json`, or `application/problem+json` for errors. Never inferred. Plus `Referrer-Policy: no-referrer`, `Cache-Control: no-store`. |
| No sensitive data in responses | ✅/🛠️ | Password hashes never leave the identity module. 🛠️ **Validation errors echoed the submitted input, including passwords.** They now return only `loc`, `msg`, `type` (tested). |
| Proper status codes | ✅ | 200/201/204, 400 (bad host), 401 (+`WWW-Authenticate`), 404, 409, 413, 422, 429 (+`Retry-After`), 502/503 for upstream failures. RFC 9457 problem+json bodies. |

## Monitoring

| Item | Status | Where / how |
|---|---|---|
| Centralized logging | ✅/🏗️ | Structured JSON logs to stdout with `request_id`, method, path, status, duration and client IP. Ship stdout to your log platform (Loki, CloudWatch, ELK). Production enforces JSON logs. |
| Monitor requests, responses, errors | ✅/🏗️ | Access log per request. `app_error`/`unhandled_error` events. Security events: `rate_limited`, `401`/`429` on `/auth/token`, `rate_limiter_unavailable`, `fatsecret_unavailable`. **Next step:** OpenTelemetry traces + metrics (latency, error rate) and Sentry for exceptions. |
| Alerts (Slack, email, …) | 🏗️ | Alert on: 5xx rate, `rate_limiter_unavailable`, spikes of `429`/`401` on `/auth/token` (credential stuffing), `fatsecret_unavailable`, `/health/ready` failing. Configure in the log/metrics platform. |
| No sensitive data in logs | ✅/🛠️ | Bodies, tokens and emails are never logged. 🛠️ A redaction processor blanks any field named like password/secret/token/authorization/api_key/cookie, even in nested data (safety net, tested). |
| IDS/IPS | 🏗️ | Not an application concern: use a WAF/IDS in front (Cloudflare/AWS WAF with managed rules, or CrowdSec reading the access logs). The JSON access log has the fields they need. |

## Known trade-offs

- **The limiter fails open.** If Redis is down, throttling and login lockout are
  skipped so users aren't locked out. Argon2 still slows guessing, and the
  `rate_limiter_unavailable` error log should page someone.
- **Fixed windows** allow up to 2× the limit around a window boundary. That's
  acceptable for abuse protection.
- **Client IP behind proxies:** throttling and lockout key on the client IP that
  uvicorn sees. Trust `X-Forwarded-For` only from your proxy (`FORWARDED_ALLOW_IPS`).
  Otherwise every request appears to come from the proxy, or attackers can spoof IPs.
- **Client IPs are logged** for security monitoring. Under GDPR that's legitimate
  interest, but define a retention period (e.g. 30 days) in your privacy policy.

## Reporting a vulnerability

Please email security@<your-domain> instead of opening a public issue.
