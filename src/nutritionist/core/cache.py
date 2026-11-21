"""Minimal async key/value cache port with Redis and in-memory adapters."""

import time
from typing import Protocol

from redis.asyncio import Redis


def redis_client(url: str, socket_timeout: float = 0.5) -> Redis:
    """Redis is an accelerator here: fail fast instead of making requests wait."""
    return Redis.from_url(
        url,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_timeout,
        health_check_interval=30,
    )


class Cache(Protocol):
    async def get(self, key: str) -> bytes | None: ...

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None: ...

    async def ping(self) -> bool: ...

    async def aclose(self) -> None: ...


class RedisCache:
    def __init__(self, client: Redis) -> None:
        self._client = client

    @classmethod
    def from_url(cls, url: str, socket_timeout: float = 0.5) -> "RedisCache":
        return cls(redis_client(url, socket_timeout))

    async def get(self, key: str) -> bytes | None:
        value = await self._client.get(key)
        return value.encode() if isinstance(value, str) else value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        await self._client.set(key, value, ex=ttl_seconds or None)

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception:
            return False

    async def aclose(self) -> None:
        await self._client.aclose()


class InMemoryCache:
    """Process-local cache. Fine for tests and local dev, never for multi-instance prod."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[bytes, float | None]] = {}

    async def get(self, key: str) -> bytes | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if expires_at is not None and expires_at <= time.monotonic():
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: bytes, ttl_seconds: int) -> None:
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds else None
        self._store[key] = (value, expires_at)

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self._store.clear()
