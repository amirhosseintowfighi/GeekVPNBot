"""Redis-backed storage for issued captcha challenges.

A challenge must survive between the request that issued it and the request that
answers it, and must expire on its own. Redis with a TTL is the whole design; a
row in Postgres would need a sweeper and would put write load on the primary for
data that is worthless in three minutes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from geekvpn.infrastructure.security.captcha import TTL_SECONDS, Challenge, ChallengeKind

logger = logging.getLogger(__name__)


class RedisCaptchaStore:
    """Stores challenges as JSON under a per-challenge key."""

    __slots__ = ("_namespace", "_redis")

    def __init__(self, redis: Redis, *, namespace: str = "geekvpn:captcha") -> None:
        self._redis = redis
        self._namespace = namespace

    def _key(self, challenge_id: str) -> str:
        return f"{self._namespace}:{challenge_id}"

    async def put(self, challenge: Challenge, *, ttl_seconds: int = TTL_SECONDS) -> None:
        payload = json.dumps(
            {
                "id": challenge.challenge_id,
                "kind": str(challenge.kind),
                "question_fa": challenge.question_fa,
                "answer": challenge.answer,
                "issued_at": challenge.issued_at.isoformat(),
                "attempts": challenge.attempts,
            }
        )
        try:
            # The TTL is the enforcement mechanism, not a courtesy: even if the
            # application forgets to delete a solved challenge, it cannot be
            # replayed tomorrow.
            await self._redis.set(self._key(challenge.challenge_id), payload, ex=ttl_seconds)
        except RedisError:
            # Failing closed here is right: a challenge that cannot be stored
            # can never be verified, so pretending it was issued would show the
            # user a puzzle that is guaranteed to be rejected.
            logger.warning("captcha.store_failed", exc_info=True)
            raise

    async def get(self, challenge_id: str) -> Challenge | None:
        try:
            raw = await self._redis.get(self._key(challenge_id))
        except RedisError:
            logger.warning("captcha.read_failed", exc_info=True)
            return None
        if not raw:
            return None
        data = json.loads(raw)
        return Challenge(
            challenge_id=data["id"],
            kind=ChallengeKind(data["kind"]),
            question_fa=data["question_fa"],
            answer=int(data["answer"]),
            issued_at=datetime.fromisoformat(data["issued_at"]),
            attempts=int(data["attempts"]),
        )

    async def delete(self, challenge_id: str) -> None:
        try:
            await self._redis.delete(self._key(challenge_id))
        except RedisError:
            logger.warning("captcha.delete_failed", exc_info=True)


__all__ = ["RedisCaptchaStore"]
