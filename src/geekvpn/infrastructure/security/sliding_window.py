"""Atomic sliding-window rate limiting, plus lockout and captcha gating.

Why the existing fixed-window limiter was not enough
---------------------------------------------------
``rate_limit.py`` counts with ``INCR`` against a key that expires. That is cheap
and correct on average, and wrong exactly where it matters: a caller can spend
the whole quota in the last moment of one window and the whole quota again in
the first moment of the next, so the real short-term ceiling is **twice** the
configured limit. On ``auth.login`` that turns a limit of five into ten guesses
back to back.

A sorted set keyed by timestamp has no such boundary. Each hit is a member
scored with the current time; everything older than the window is dropped before
counting. The whole read-drop-count-write sequence runs inside one Lua script,
so it is atomic even with many workers - a check-then-set in Python would race
and under-count under exactly the concurrency an attacker creates.

Failure posture
---------------
This limiter **fails open** on a Redis outage, matching the existing limiter and
the revocation list. That is a real, deliberate trade: with Redis down, either
logins are refused for everyone (a self-inflicted outage) or they are allowed
unthrottled (a window for guessing). Refusing all payments and all logins
because a cache is unavailable is the larger harm. Every failure is logged at
warning level so the window is visible rather than silent, and the account
lockout counter lives in Postgres, not here, so the strongest control survives a
Redis outage.
"""

from __future__ import annotations

import logging
import time
from typing import Final

from redis.asyncio import Redis
from redis.exceptions import RedisError

from geekvpn.application.ports.rate_limiter import RateLimitVerdict
from geekvpn.infrastructure.security.throttling import Decision, Policy, combine, keys_for

logger = logging.getLogger(__name__)

#: KEYS[1] = counter key
#: ARGV = now_ms, window_ms, limit, cost, member_prefix
#:
#: Returns {allowed, remaining, retry_after_ms}.
#:
#: Members are unique per hit (``prefix:index``) so that two requests in the
#: same millisecond are two entries rather than one overwritten one - a plain
#: timestamp member would silently make a burst free.
_SLIDING_WINDOW_LUA: Final = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local prefix = ARGV[5]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local used = redis.call('ZCARD', key)

if used + cost > limit then
  local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
  local retry = window
  if oldest[2] then
    retry = (tonumber(oldest[2]) + window) - now
    if retry < 1 then retry = 1 end
  end
  -- The refused hit is not recorded. Recording it would let a client that
  -- keeps hammering push its own reset time forever into the future, which
  -- turns a rate limit into a permanent self-ban.
  return {0, limit - used, retry}
end

for i = 1, cost do
  redis.call('ZADD', key, now, prefix .. ':' .. i)
end
-- The TTL is refreshed on every accepted hit so an idle key disappears on its
-- own; without it, every distinct subject leaks one key forever.
redis.call('PEXPIRE', key, window)
return {1, limit - used - cost, 0}
"""


class RedisSlidingWindowLimiter:
    """Sliding-window limiter over Redis sorted sets."""

    __slots__ = ("_namespace", "_redis", "_script")

    def __init__(self, redis: Redis, *, namespace: str = "geekvpn:rl") -> None:
        self._redis = redis
        self._namespace = namespace
        # register_script uses EVALSHA with an EVAL fallback, so the script body
        # travels once rather than on every request.
        self._script = redis.register_script(_SLIDING_WINDOW_LUA)

    def _key(self, key: str) -> str:
        return f"{self._namespace}:{key}"

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> RateLimitVerdict:
        """Satisfies the existing ``RateLimiter`` port, so it is a drop-in."""
        allowed, remaining, retry_after = await self._hit(
            key, limit=limit, window_seconds=window_seconds, cost=1
        )
        return RateLimitVerdict(
            allowed=allowed, remaining=remaining, retry_after_seconds=retry_after
        )

    async def _hit(
        self, key: str, *, limit: int, window_seconds: int, cost: int
    ) -> tuple[bool, int, int]:
        now_ms = int(time.time() * 1000)
        window_ms = window_seconds * 1000
        try:
            result = await self._script(
                keys=[self._key(key)],
                args=[now_ms, window_ms, limit, cost, f"{now_ms}-{id(self):x}"],
            )
        except RedisError:
            logger.warning("ratelimit.unavailable", extra={"key": key}, exc_info=True)
            return True, limit, 0
        allowed = bool(int(result[0]))
        remaining = max(int(result[1]), 0)
        retry_after = max(int(result[2]) // 1000, 1) if not allowed else 0
        return allowed, remaining, retry_after

    async def check(
        self,
        policy: Policy,
        *,
        subject_id: str | None = None,
        ip: str | None = None,
    ) -> Decision:
        """Apply a policy across every key it implies; the strictest one wins."""
        verdicts = []
        for key in keys_for(policy, subject_id=subject_id, ip=ip):
            verdicts.append(
                await self._hit(
                    key,
                    limit=policy.limit,
                    window_seconds=policy.window_seconds,
                    cost=policy.cost,
                )
            )
        return combine(policy, tuple(verdicts))

    async def peek(
        self, policy: Policy, *, subject_id: str | None = None, ip: str | None = None
    ) -> int:
        """How many hits are currently counted, without recording one.

        Used by endpoints that must decide whether to demand a captcha before
        doing any work.
        """
        now_ms = int(time.time() * 1000)
        window_ms = policy.window_seconds * 1000
        try:
            pipe = self._redis.pipeline(transaction=False)
            keys = keys_for(policy, subject_id=subject_id, ip=ip)
            for key in keys:
                pipe.zcount(self._key(key), now_ms - window_ms, now_ms)
            counts = await pipe.execute()
            return max((int(value) for value in counts), default=0)
        except RedisError:
            logger.warning("ratelimit.peek_failed", exc_info=True)
            return 0

    async def reset(self, key: str) -> None:
        """Clear a counter. Called after a *successful* login.

        This is what makes ``failures_only`` policies humane: a customer who
        finally remembers their password is not still carrying four failures.
        """
        try:
            await self._redis.delete(self._key(key))
        except RedisError:
            logger.warning("ratelimit.reset_failed", extra={"key": key}, exc_info=True)

    async def reset_policy(
        self, policy: Policy, *, subject_id: str | None = None, ip: str | None = None
    ) -> None:
        for key in keys_for(policy, subject_id=subject_id, ip=ip):
            await self.reset(key)


__all__ = ["RedisSlidingWindowLimiter"]
