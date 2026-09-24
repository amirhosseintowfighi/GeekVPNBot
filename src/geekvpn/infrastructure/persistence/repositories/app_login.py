"""App sign-in requests (see `AppLinkLogin`).

Every transition is a conditional UPDATE whose WHERE clause restates the
state it moves out of, and the caller learns from `rowcount` whether it won.
Under READ COMMITTED a second writer blocks on the row lock, re-evaluates the
predicate and matches nothing - so two taps on "approve", or two polls racing
for the same tokens, cannot both succeed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from geekvpn.domain.identity.app_login import AppLoginRequest, AppLoginStatus
from geekvpn.infrastructure.persistence.models.identity import AppLoginRequestModel

_Row = AppLoginRequestModel


class SqlAlchemyAppLoginRepository:
    """Implements `AppLoginRepository` over PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    async def add(self, request: AppLoginRequest) -> None:
        self._db.add(_Row.from_domain(request))
        await self._db.flush()

    async def get(self, request_id: uuid.UUID) -> AppLoginRequest | None:
        row = await self._db.get(_Row, request_id)
        return row.to_domain() if row is not None else None

    async def get_by_code_hash(self, code_hash: str) -> AppLoginRequest | None:
        return await self._one(_Row.code_hash == code_hash)

    async def get_by_poll_token_hash(self, poll_token_hash: str) -> AppLoginRequest | None:
        return await self._one(_Row.poll_token_hash == poll_token_hash)

    async def claim(self, request_id: uuid.UUID, *, telegram_user_id: int, now: datetime) -> bool:
        return await self._transition(
            request_id,
            _Row.status == AppLoginStatus.PENDING.value,
            _Row.telegram_user_id.is_(None),
            _Row.expires_at > now,
            values={"telegram_user_id": telegram_user_id},
        )

    async def decide(
        self,
        request_id: uuid.UUID,
        *,
        telegram_user_id: int,
        status: AppLoginStatus,
        now: datetime,
    ) -> bool:
        return await self._transition(
            request_id,
            _Row.status == AppLoginStatus.PENDING.value,
            _Row.telegram_user_id == telegram_user_id,
            _Row.expires_at > now,
            values={"status": status.value},
        )

    async def consume(self, request_id: uuid.UUID, *, now: datetime) -> bool:
        return await self._transition(
            request_id,
            _Row.status == AppLoginStatus.APPROVED.value,
            _Row.expires_at > now,
            values={"status": AppLoginStatus.CONSUMED.value},
        )

    async def _one(self, condition: ColumnElement[bool]) -> AppLoginRequest | None:
        row = (await self._db.execute(select(_Row).where(condition))).scalar_one_or_none()
        return row.to_domain() if row is not None else None

    async def _transition(
        self,
        request_id: uuid.UUID,
        *conditions: ColumnElement[bool],
        values: dict[str, Any],
    ) -> bool:
        # An UPDATE yields a CursorResult, which is what carries rowcount; the
        # declared Result type does not.
        result = cast(
            "CursorResult[Any]",
            await self._db.execute(
                update(_Row).where(_Row.id == request_id, *conditions).values(**values)
            ),
        )
        await self._db.flush()
        return bool(result.rowcount == 1)
