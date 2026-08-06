"""Redis rate limiting.

Algorithm: fixed window with an atomic INCR. Chosen over a sliding log because
it costs one round trip and O(1) memory per key, and over a token bucket
because it needs no Lua and no clock synchronisation.

Known trade-off: a burst can straddle a window boundary and briefly allow up to
2x the limit. For login throttling that is irrelevant - the attacker still
cannot get more than ~2x over any sustained period, and we lock the account
separately. For money endpoints in a later phase, use idempotency keys, not
rate limits.

Fails **open** on a Redis outage: Redis being down must not lock every admin
out of the panel during an incident. Every such event is logged loudly.
"""

from __future__ import annotations

from redis.asyncio import Redis
from redis.exceptions import RedisError

from geekvpn.application.ports.rate_limiter import RateLimitVerdict
from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger(__name__)


class RedisRateLimiter:
    def __init__(self, redis: Redis, *, namespace: str = "geekvpn:ratelimit") -> None:
        self._redis = redis
        self._namespace = namespace

    def _key(self, key: str) -> str:
        return f"{self._namespace}:{key}"

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitVerdict:
        redis_key = self._key(key)
        try:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.incr(redis_key)
                pipe.ttl(redis_key)
                count, ttl = await pipe.execute()

            if ttl is None or ttl < 0:
                # First hit in this window (or a key that lost its TTL).
                await self._redis.expire(redis_key, window_seconds)
                ttl = window_seconds
        except RedisError:
            logger.error("ratelimit.unavailable", key=key, exc_info=True)
            return RateLimitVerdict(allowed=True, remaining=limit, retry_after_seconds=0)

        remaining = max(limit - int(count), 0)
        return RateLimitVerdict(
            allowed=int(count) <= limit,
            remaining=remaining,
            retry_after_seconds=int(ttl) if remaining == 0 else 0,
        )

    async def reset(self, key: str) -> None:
        try:
            await self._redis.delete(self._key(key))
        except RedisError:  # pragma: no cover - best effort
            logger.warning("ratelimit.reset_failed", key=key)
