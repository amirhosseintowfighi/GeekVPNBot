"""Runtime settings store: Postgres for truth, Redis for speed.

Settings are read on many requests and written a handful of times a year, so
they are cached aggressively and the cache is invalidated on write. The cache
is a pure optimisation: every path works correctly with Redis down.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.ports.settings_store import SettingRecord
from geekvpn.infrastructure.logging.setup import get_logger
from geekvpn.infrastructure.persistence.models.settings import SettingModel

logger = get_logger(__name__)

CACHE_TTL_SECONDS = 300


class DbSettingsStore:
    def __init__(
        self,
        session: AsyncSession,
        *,
        redis: Redis | None = None,
        namespace: str = "geekvpn:setting",
    ) -> None:
        self._session = session
        self._redis = redis
        self._namespace = namespace

    async def get(self, key: str) -> SettingRecord | None:
        cached = await self._cache_get(key)
        if cached is not None:
            return cached

        model = await self._session.get(SettingModel, key)
        if model is None:
            return None

        record = _to_record(model)
        await self._cache_set(record)
        return record

    async def all(self) -> Sequence[SettingRecord]:
        stmt = select(SettingModel).order_by(SettingModel.key)
        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_record(model) for model in models]

    async def set(
        self,
        key: str,
        value: Any,
        *,
        updated_by: uuid.UUID | None = None,
        description: str | None = None,
        is_secret: bool = False,
    ) -> SettingRecord:
        """Upsert. Concurrent writers cannot produce a duplicate-key error."""
        now = datetime.now(UTC)
        stmt = (
            insert(SettingModel)
            .values(
                key=key,
                value=value,
                description=description,
                is_secret=is_secret,
                updated_by=updated_by,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[SettingModel.key],
                set_={
                    "value": value,
                    "description": description,
                    "is_secret": is_secret,
                    "updated_by": updated_by,
                    "updated_at": now,
                },
            )
            .returning(SettingModel)
        )
        model = (await self._session.execute(stmt)).scalar_one()
        await self._session.flush()

        record = _to_record(model)
        await self._cache_invalidate(key)
        return record

    async def delete(self, key: str) -> bool:
        model = await self._session.get(SettingModel, key)
        if model is None:
            return False
        await self._session.delete(model)
        await self._session.flush()
        await self._cache_invalidate(key)
        return True

    # -- cache -------------------------------------------------------------

    def _cache_key(self, key: str) -> str:
        return f"{self._namespace}:{key}"

    async def _cache_get(self, key: str) -> SettingRecord | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(self._cache_key(key))
        except RedisError:
            logger.warning("settings.cache_read_failed", key=key)
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            return SettingRecord(
                key=key,
                value=payload["value"],
                description=payload.get("description"),
                is_secret=payload.get("is_secret", False),
            )
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    async def _cache_set(self, record: SettingRecord) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(
                self._cache_key(record.key),
                json.dumps(
                    {
                        "value": record.value,
                        "description": record.description,
                        "is_secret": record.is_secret,
                    }
                ),
                ex=CACHE_TTL_SECONDS,
            )
        except (RedisError, TypeError):  # pragma: no cover - best effort
            logger.warning("settings.cache_write_failed", key=record.key)

    async def _cache_invalidate(self, key: str) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.delete(self._cache_key(key))
        except RedisError:  # pragma: no cover
            logger.warning("settings.cache_invalidate_failed", key=key)


def _to_record(model: SettingModel) -> SettingRecord:
    return SettingRecord(
        key=model.key,
        value=model.value,
        description=model.description,
        is_secret=model.is_secret,
        updated_at=model.updated_at,
        updated_by=model.updated_by,
    )
