"""Redis-backed revocation list. See the port for the rationale."""

from __future__ import annotations

import uuid
from datetime import datetime

from redis.asyncio import Redis
from redis.exceptions import RedisError

from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger(__name__)


class RedisRevocationList:
    def __init__(self, redis: Redis, *, namespace: str = "geekvpn:revoked") -> None:
        self._redis = redis
        self._namespace = namespace

    def _session_key(self, session_id: uuid.UUID) -> str:
        return f"{self._namespace}:session:{session_id}"

    def _subject_key(self, subject_id: uuid.UUID) -> str:
        return f"{self._namespace}:subject:{subject_id}"

    async def revoke_session(self, session_id: uuid.UUID, *, ttl_seconds: int) -> None:
        try:
            await self._redis.set(self._session_key(session_id), "1", ex=max(ttl_seconds, 1))
        except RedisError:
            # The database row is already revoked, so the session dies at the
            # next refresh regardless. Only the immediacy is lost.
            logger.error("revocation.publish_failed", session_id=str(session_id))

    async def revoke_subject(
        self, subject_id: uuid.UUID, *, at: datetime, ttl_seconds: int
    ) -> None:
        try:
            await self._redis.set(
                self._subject_key(subject_id),
                str(at.timestamp()),
                ex=max(ttl_seconds, 1),
            )
        except RedisError:
            logger.error("revocation.publish_failed", subject_id=str(subject_id))

    async def is_revoked(
        self, *, session_id: uuid.UUID, subject_id: uuid.UUID, issued_at: datetime
    ) -> bool:
        try:
            async with self._redis.pipeline(transaction=False) as pipe:
                pipe.get(self._session_key(session_id))
                pipe.get(self._subject_key(subject_id))
                session_flag, subject_epoch = await pipe.execute()
        except RedisError:
            logger.error("revocation.check_failed", session_id=str(session_id))
            return False  # fail open, deliberately

        if session_flag is not None:
            return True
        if subject_epoch is None:
            return False
        try:
            epoch = float(subject_epoch)
        except (TypeError, ValueError):  # pragma: no cover - corrupt value
            return False
        # Tokens minted before the mass-revocation are dead; ones minted after
        # it (a fresh login) are fine.
        return issued_at.timestamp() < epoch
