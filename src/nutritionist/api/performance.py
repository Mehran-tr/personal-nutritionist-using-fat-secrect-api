"""Response-level performance: Prometheus HTTP metrics and ETag/304 revalidation.
(Compression is Starlette's GZipMiddleware, configured in ``main``.)"""

import hashlib
import time

from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nutritionist.api.hardening import internal_network_only
from nutritionist.core.metrics import HTTP_LATENCY, HTTP_REQUESTS

MAX_ETAG_BODY_BYTES = 1024 * 1024


class MetricsMiddleware:
    """Counts and times every request by route *template* (e.g. /me/diary/{day})."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        status = 500
        started = time.perf_counter()

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            route = route_template(scope)
            method = scope["method"]
            HTTP_REQUESTS.labels(method, route, str(status)).inc()
            HTTP_LATENCY.labels(method, route).observe(time.perf_counter() - started)


def route_template(scope: Scope) -> str:
    """``/api/v1/me/diary/2026-11-20`` -> ``/api/v1/me/diary/{day}``.

    Built from the full path and the matched path parameters, so it includes
    router prefixes, and unmatched paths (404 scans) collapse into one label
    instead of exploding cardinality.
    """
    if scope.get("route") is None:
        return "unmatched"
    params = {str(v): f"{{{k}}}" for k, v in scope.get("path_params", {}).items()}
    return "/".join(params.get(segment, segment) for segment in scope["path"].split("/"))


class ETagMiddleware:
    """Weak ETags for successful GET responses, and ``304 Not Modified`` when the
    client already has the current version. Saves bandwidth and client parsing
    for polling-style reads (diary day, targets, coach) without any per-route code.
    Bodies are small JSON, so buffering one to hash it is cheap."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "GET":
            await self.app(scope, receive, send)
            return

        if_none_match = Headers(scope=scope).get("if-none-match")
        start: Message | None = None
        chunks: list[bytes] = []
        passthrough = False

        async def buffer(message: Message) -> None:
            nonlocal start, passthrough
            if passthrough:
                await send(message)
                return
            if message["type"] == "http.response.start":
                start = message
                if message["status"] != 200:
                    passthrough = True
                    await send(message)
                return
            if message["type"] != "http.response.body":
                await send(message)
                return

            chunks.append(message.get("body", b""))
            size = sum(map(len, chunks))
            if size > MAX_ETAG_BODY_BYTES:  # too big to buffer: stream it as-is
                passthrough = True
                assert start is not None
                await send(start)
                await send({**message, "body": b"".join(chunks)})
                return
            if message.get("more_body", False):
                return

            assert start is not None
            body = b"".join(chunks)
            etag = f'W/"{hashlib.blake2b(body, digest_size=16).hexdigest()}"'
            headers = MutableHeaders(scope=start)
            headers["ETag"] = etag
            if if_none_match and etag in {t.strip() for t in if_none_match.split(",")}:
                start["status"] = 304
                del headers["content-length"]
                if "content-type" in headers:
                    del headers["content-type"]
                await send(start)
                await send({"type": "http.response.body", "body": b""})
                return
            await send(start)
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, buffer)


metrics_router = APIRouter(tags=["ops"], include_in_schema=False)


@metrics_router.get("/metrics", dependencies=[Depends(internal_network_only)])
async def metrics() -> Response:
    """Prometheus scrape endpoint (internal networks only)."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
