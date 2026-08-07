"""Redis client factory and the ``Cache`` port implementation."""

from __future__ import annotations

from redis.asyncio import ConnectionPool, Redis

from geekvpn.infrastructure.config.settings import RedisSettings


def create_redis(settings: RedisSettings) -> Redis:
    pool = ConnectionPool.from_url(
        settings.dsn(),
        max_connections=settings.max_connections,
        socket_timeout=settings.socket_timeout_seconds,
        socket_connect_timeout=settings.socket_timeout_seconds,
        decode_responses=True,
        health_check_interval=30,
    )
    return Redis(connection_pool=pool)


class RedisCache:
    """Concrete implementation of ``application.ports.Cache``."""

    def __init__(self, client: Redis, *, namespace: str = "geekvpn") -> None:
        self._client = client
        self._namespace = namespace

    def _key(self, key: str) -> str:
        return f"{self._namespace}:{key}"

    async def get(self, key: str) -> str | None:
        # The client is built with decode_responses=True, which the stubs
        # cannot express, so the declared type still admits bytes.
        value = await self._client.get(self._key(key))
        return None if value is None else str(value)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        await self._client.set(self._key(key), value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._client.delete(self._key(key))

    async def add_if_absent(self, key: str, value: str, *, ttl_seconds: int) -> bool:
        created = await self._client.set(self._key(key), value, ex=ttl_seconds, nx=True)
        return bool(created)
