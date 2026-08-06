"""Redis-backed analytics report cache with single-flight recomputation.

Closes a real gap: ``application/analytics/ports.py`` has declared a
``ReportCache`` protocol since Phase 11 and nothing ever implemented it, so every
dashboard load ran eight aggregate queries against Postgres. A declared port with
no implementation is worse than no port, because the architecture diagram claims
the caching exists.

Failure posture: **fail open on read, fail open on write.** If Redis is down the
dashboard gets slow, not broken. That is the opposite of the choice made for the
captcha store, and the difference is deliberate - losing a captcha challenge
weakens a control, losing a cached report weakens nothing.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final

from redis.asyncio import Redis

from geekvpn.infrastructure.cache.keys import (
    LOCK_TTL_SECONDS,
    build_key,
    jittered_ttl,
    lock_key,
    ttl_for,
)

logger = logging.getLogger(__name__)

#: How long a waiting request will sit for the leader to finish before giving up
#: and computing the value itself. Longer than a typical aggregate query, shorter
#: than any sane HTTP timeout.
_WAIT_TIMEOUT_SECONDS: Final = 5.0
_WAIT_INTERVAL_SECONDS: Final = 0.05


class RedisReportCache:
    """Implements ``application.analytics.ports.ReportCache``."""

    __slots__ = ("_namespace", "_redis")

    def __init__(self, redis: Redis, *, namespace: str = "report") -> None:
        self._redis = redis
        self._namespace = namespace

    def key_for(self, kind: str, **parts: Any) -> str:
        return build_key(f"{self._namespace}.{kind}", **parts)

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._redis.get(key)
        except Exception:
            logger.warning("reportcache.read_failed", extra={"key": key}, exc_info=True)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            # A value we cannot read is a value we do not have. Deleting it stops
            # the same poison entry being decoded on every request for an hour.
            logger.warning("reportcache.corrupt_entry", extra={"key": key})
            await self.invalidate(key)
            return None

    async def set(self, key: str, value: Any, *, kind: str) -> None:
        try:
            payload = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            logger.warning("reportcache.unserialisable", extra={"key": key})
            return
        try:
            await self._redis.set(key, payload, ex=jittered_ttl(ttl_for(kind)))
        except Exception:
            logger.warning("reportcache.write_failed", extra={"key": key}, exc_info=True)

    async def invalidate(self, key: str) -> None:
        try:
            await self._redis.delete(key)
        except Exception:
            logger.warning("reportcache.invalidate_failed", extra={"key": key}, exc_info=True)

    async def invalidate_prefix(self, pattern: str) -> int:
        """Delete matching keys with ``SCAN``, never ``KEYS``.

        ``KEYS`` blocks the server for the length of the keyspace walk. On a
        production instance that is an outage triggered by a cache flush.
        """
        removed = 0
        try:
            async for found in self._redis.scan_iter(match=pattern, count=200):
                await self._redis.delete(found)
                removed += 1
        except Exception:
            logger.warning(
                "reportcache.prefix_invalidate_failed", extra={"pattern": pattern}, exc_info=True
            )
        return removed

    async def get_or_compute(
        self, key: str, *, kind: str, compute: Callable[[], Awaitable[Any]]
    ) -> Any:
        """Return the cached value, or compute it exactly once across all workers.

        The sequence is: read; on a miss try to take the lock; the winner
        computes and stores; the losers wait briefly and re-read. A loser that
        times out computes the value itself rather than failing, because a slow
        answer beats an error page and a stuck lock must not be able to take the
        dashboard down.
        """
        cached = await self.get(key)
        if cached is not None:
            return cached

        lock = lock_key(key)
        got_lock = False
        try:
            got_lock = bool(await self._redis.set(lock, "1", ex=LOCK_TTL_SECONDS, nx=True))
        except Exception:
            # No lock available means no coordination, not no answer.
            logger.warning("reportcache.lock_failed", extra={"key": key}, exc_info=True)
            got_lock = True

        if got_lock:
            try:
                value = await compute()
                await self.set(key, value, kind=kind)
                return value
            finally:
                await self.invalidate(lock)

        waited = 0.0
        while waited < _WAIT_TIMEOUT_SECONDS:
            await asyncio.sleep(_WAIT_INTERVAL_SECONDS)
            waited += _WAIT_INTERVAL_SECONDS
            value = await self.get(key)
            if value is not None:
                return value
        logger.info("reportcache.lock_wait_timeout", extra={"key": key})
        return await compute()

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """One round trip for many keys.

        A dashboard reads eight cards. Eight sequential ``GET`` calls is eight
        network round trips; on a managed Redis with 2ms latency that is 16ms of
        pure waiting per page load, which is more than the queries cost.
        """
        if not keys:
            return {}
        try:
            values = await self._redis.mget(keys)
        except Exception:
            logger.warning("reportcache.mget_failed", exc_info=True)
            return {}
        found: dict[str, Any] = {}
        for key, raw in zip(keys, values, strict=False):
            if raw is None:
                continue
            try:
                found[key] = json.loads(raw)
            except (TypeError, ValueError):
                logger.warning("reportcache.corrupt_entry", extra={"key": key})
        return found

    async def warm(self, entries: dict[str, Any], *, kind: str) -> None:
        """Write many entries in one pipeline, for a scheduled warm-up job.

        ``transaction=False``: these writes are independent, and wrapping them in
        MULTI/EXEC would block other clients for the duration for no benefit.
        """
        if not entries:
            return
        try:
            pipe = self._redis.pipeline(transaction=False)
            for key, value in entries.items():
                pipe.set(
                    key,
                    json.dumps(value, ensure_ascii=False, default=str),
                    ex=jittered_ttl(ttl_for(kind)),
                )
            await pipe.execute()
        except Exception:
            logger.warning("reportcache.warm_failed", exc_info=True)


__all__ = ["RedisReportCache"]
