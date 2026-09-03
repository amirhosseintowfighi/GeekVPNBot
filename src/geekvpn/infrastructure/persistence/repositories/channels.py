"""Required-channel rows, scoped to one shop.

Every method takes the shop from the repository rather than from the caller,
the way the other tenant-aware repositories here do. A method that let the
caller pass one would be a forgotten argument away from a reseller editing the
platform's gate.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from geekvpn.application.platform.channel_gate import RequiredChannel
from geekvpn.infrastructure.persistence.models import RequiredChannelModel


class SqlRequiredChannelRepository:
    def __init__(self, session: AsyncSession, *, reseller_id: uuid.UUID | None = None) -> None:
        self._session = session
        self._reseller_id = reseller_id

    def _shop(self) -> ColumnElement[bool]:
        return RequiredChannelModel.reseller_id == self._reseller_id

    async def active(self) -> list[RequiredChannel]:
        """What the bot gates on. Ordered so the buttons are stable."""
        rows = await self._session.execute(
            select(RequiredChannelModel)
            .where(self._shop(), RequiredChannelModel.active.is_(True))
            .order_by(RequiredChannelModel.sort_order, RequiredChannelModel.id)
        )
        return [_to_domain(row) for row in rows.scalars().all()]

    async def listing(self) -> list[dict[str, object]]:
        """What the operator sees, inactive rows included.

        A switched-off channel is still a row they configured, and hiding it
        would look like it had been deleted.
        """
        rows = await self._session.execute(
            select(RequiredChannelModel)
            .where(self._shop())
            .order_by(RequiredChannelModel.sort_order, RequiredChannelModel.id)
        )
        return [
            {
                "id": row.id,
                "chat_ref": row.chat_ref,
                "title_fa": row.title_fa,
                "invite_url": row.invite_url,
                "active": row.active,
                "sort_order": row.sort_order,
            }
            for row in rows.scalars().all()
        ]

    async def add(
        self, *, chat_ref: str, title_fa: str, invite_url: str | None
    ) -> None:
        self._session.add(
            RequiredChannelModel(
                id=uuid.uuid4().hex,
                chat_ref=chat_ref,
                title_fa=title_fa,
                invite_url=invite_url or None,
                active=True,
                sort_order=0,
                reseller_id=self._reseller_id,
            )
        )
        await self._session.flush()

    async def set_active(self, channel_id: str, *, active: bool) -> bool:
        """The shop is in the WHERE, so a guessed id belonging to another shop
        changes nothing rather than answering "not found" and confirming it."""
        result: CursorResult[Any] = await self._session.execute(  # type: ignore[assignment]
            update(RequiredChannelModel)
            .where(self._shop(), RequiredChannelModel.id == channel_id)
            .values(active=active)
        )
        await self._session.flush()
        return bool(result.rowcount)

    async def remove(self, channel_id: str) -> bool:
        """A real delete. Unlike a plan or a coupon, nothing references this
        afterwards - it is a rule that applied while it existed."""
        result: CursorResult[Any] = await self._session.execute(  # type: ignore[assignment]
            delete(RequiredChannelModel).where(
                self._shop(), RequiredChannelModel.id == channel_id
            )
        )
        await self._session.flush()
        return bool(result.rowcount)


def _to_domain(row: RequiredChannelModel) -> RequiredChannel:
    return RequiredChannel(
        id=row.id,
        chat_ref=row.chat_ref,
        title_fa=row.title_fa,
        invite_url=row.invite_url,
    )


__all__: Sequence[str] = ["SqlRequiredChannelRepository"]
