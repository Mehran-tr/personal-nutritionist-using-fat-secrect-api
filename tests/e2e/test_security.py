"""The API security checklist, verified against the running app."""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from nutritionist.bootstrap import Container, build_container
from nutritionist.core.config import Settings
from nutritionist.main import create_app
from tests.fakes import FakeFoodProvider

PASSWORD = "correct horse battery"


@contextmanager
def app_client(
    settings: Settings, ip: str = "10.0.0.7", **security: object
) -> Iterator[TestClient]:
    configured = settings.model_copy(
        update={"security": settings.security.model_copy(update=security)}
    )

    async def factory(s: Settings) -> Container:
        return await build_container(s, food_provider=FakeFoodProvider())

    with TestClient(create_app(configured, container_factory=factory), client=(ip, 1)) as c:
        yield c


def _register(client: TestClient, email: str = "s@example.com") -> None:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201


# ------------------------------------------------------------------ output headers


@pytest.mark.parametrize("path", ["/health/live", "/api/v1/me", "/api/v1/does-not-exist"])
def test_security_headers_on_every_response(client: TestClient, path: str) -> None:
    headers = client.get(path).headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["content-security-policy"].startswith("default-src 'none'")
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["cache-control"] == "no-store"
    assert "server" not in headers
    assert "x-powered-by" not in headers
    assert "strict-transport-security" not in headers  # off unless served over HTTPS


def test_hsts_when_enabled(settings: Settings, database: None) -> None:
    with app_client(settings, hsts_enabled=True) as c:
        hsts = c.get("/health/live").headers["strict-transport-security"]
    assert hsts == "max-age=63072000; includeSubDomains"


def test_docs_get_a_csp_that_lets_swagger_load(client: TestClient) -> None:
    csp = client.get("/docs").headers["content-security-policy"]
    assert "cdn.jsdelivr.net" in csp
    assert "frame-ancestors 'none'" in csp


def test_responses_have_explicit_content_types(client: TestClient) -> None:
    assert client.get("/health/live").headers["content-type"] == "application/json"
    assert client.get("/api/v1/me").headers["content-type"] == "application/problem+json"


# ------------------------------------------------------------------ sensitive data


def test_validation_errors_never_echo_input(client: TestClient) -> None:
    secret = "Sh0rt!"
    response = client.post("/api/v1/auth/register", json={"email": "a@b.de", "password": secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert set(response.json()["errors"][0]) == {"loc", "msg", "type"}


def test_token_carries_no_sensitive_claims(client: TestClient) -> None:
    import jwt

    _register(client)
    token = client.post(
        "/api/v1/auth/token", json={"email": "s@example.com", "password": PASSWORD}
    ).json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    assert set(claims) == {"sub", "iss", "aud", "iat", "exp", "jti"}
    assert "s@example.com" not in token


# ------------------------------------------------------------------ access control


def test_every_non_public_endpoint_requires_a_token(client: TestClient) -> None:
    public = {"/health/live", "/health/ready", "/api/v1/auth/register", "/api/v1/auth/token"}
    spec = client.get("/openapi.json").json()
    checked = 0
    for path, operations in spec["paths"].items():
        if path in public:
            continue
        concrete = (
            path.replace("{food_id}", "1")
            .replace("{barcode}", "4006381333931")
            .replace("{day}", "2026-01-01")
            .replace("{entry_id}", "00000000-0000-0000-0000-000000000000")
        )
        for method in operations:
            response = client.request(method.upper(), concrete, json={})
            assert response.status_code == 401, f"{method.upper()} {path} is not protected"
            checked += 1
    assert checked >= 10


def test_readiness_is_internal_only(settings: Settings, database: None) -> None:
    with app_client(settings, ip="203.0.113.50") as public:
        assert public.get("/health/ready").status_code == 404
        assert public.get("/health/live").status_code == 200
    with app_client(settings, ip="10.1.2.3") as internal:
        assert internal.get("/health/ready").status_code == 200


def test_unknown_host_header_is_rejected(settings: Settings, database: None) -> None:
    with app_client(settings, allowed_hosts=["api.example.com", "testserver"]) as c:
        assert c.get("/health/live").status_code == 200
        assert c.get("/health/live", headers={"host": "evil.example"}).status_code == 400


# ------------------------------------------------------------------ throttling & max retry


def test_auth_routes_are_throttled_per_ip(settings: Settings, database: None) -> None:
    with app_client(settings, auth_rate_limit_per_minute=3) as c:
        codes = [
            c.post("/api/v1/auth/token", json={"email": "x@y.de", "password": "x"}).status_code
            for _ in range(4)
        ]
        limited = c.post("/api/v1/auth/token", json={"email": "x@y.de", "password": "x"})
    assert codes == [401, 401, 401, 429]
    assert limited.headers["retry-after"].isdigit()
    assert limited.headers["x-content-type-options"] == "nosniff"
    assert limited.json()["type"] == "/problems/too_many_requests"


def test_general_throttling(settings: Settings, database: None) -> None:
    with app_client(settings, rate_limit_per_minute=2) as c:
        codes = [c.get("/api/v1/me").status_code for _ in range(3)]
        assert c.get("/health/live").status_code == 200  # probes are never throttled
    assert codes == [401, 401, 429]


def test_login_max_retry_then_jail(client: TestClient) -> None:
    _register(client)
    wrong = {"email": "s@example.com", "password": "wrong password!"}
    assert [client.post("/api/v1/auth/token", json=wrong).status_code for _ in range(5)] == [
        401
    ] * 5

    jailed = client.post(
        "/api/v1/auth/token", json={"email": "s@example.com", "password": PASSWORD}
    )
    assert jailed.status_code == 429
    assert jailed.json()["type"] == "/problems/too_many_login_attempts"
    assert int(jailed.headers["retry-after"]) > 800  # ~15 minutes


# ------------------------------------------------------------------ processing


def test_oversized_bodies_are_rejected(client: TestClient) -> None:
    big = "x" * (65 * 1024)
    declared = client.post(
        "/api/v1/auth/register", content=big, headers={"content-type": "application/json"}
    )
    assert declared.status_code == 413
    assert declared.json()["type"] == "/problems/payload_too_large"

    def chunks() -> Iterator[bytes]:
        for _ in range(70):
            yield b"x" * 1024

    streamed = client.post(
        "/api/v1/auth/register", content=chunks(), headers={"content-type": "application/json"}
    )
    assert streamed.status_code == 413


def test_ids_in_urls_are_uuids_and_never_user_ids(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert not any("{user_id}" in path for path in spec["paths"])
    entry_param = spec["paths"]["/api/v1/me/diary/entries/{entry_id}"]["patch"]["parameters"][0]
    assert entry_param["schema"]["format"] == "uuid"
