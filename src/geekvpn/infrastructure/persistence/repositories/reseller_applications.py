"""Storage for reseller applications, and the one-time password-setup token.

Two adapters in one file because they are two halves of one decision: an
approval writes a reseller, a login, and the token that lets that login choose
its own password.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.resellers.applications import PENDING, ApplicationView
from geekvpn.application.resellers.topups import PENDING as TOPUP_PENDING
from geekvpn.application.resellers.topups import TopupView
from geekvpn.infrastructure.persistence.models.identity import AdminModel
from geekvpn.infrastructure.persistence.models.resellers import (
    ResellerApplicationModel,
    ResellerModel,
    ResellerTopupModel,
)


def _view(row: ResellerApplicationModel) -> ApplicationView:
    return ApplicationView(
        id=row.id,
        telegram_id=row.telegram_id,
        name_fa=row.name_fa,
        contact_fa=row.contact_fa,
        note_fa=row.note_fa,
        state=row.state,
        created_at=row.created_at,
    )


class SqlAlchemyApplicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, **fields: Any) -> uuid.UUID:
        row = ResellerApplicationModel(**fields)
        self._session.add(row)
        await self._session.flush()
        return row.id

    async def pending_for(self, telegram_id: int) -> ApplicationView | None:
        stmt = select(ResellerApplicationModel).where(
            ResellerApplicationModel.telegram_id == telegram_id,
            ResellerApplicationModel.state == PENDING,
        )
        row = (await self._session.execute(stmt)).scalars().first()
        return _view(row) if row else None

    async def get(self, application_id: uuid.UUID) -> ApplicationView | None:
        row = await self._session.get(ResellerApplicationModel, application_id)
        return _view(row) if row else None

    async def list_pending(self, *, limit: int = 50) -> Sequence[ApplicationView]:
        stmt = (
            select(ResellerApplicationModel)
            .where(ResellerApplicationModel.state == PENDING)
            # Oldest first: a queue somebody is waiting in.
            .order_by(ResellerApplicationModel.created_at)
            .limit(limit)
        )
        return [_view(row) for row in (await self._session.execute(stmt)).scalars().all()]

    async def decide(
        self,
        application_id: uuid.UUID,
        *,
        state: str,
        decided_by: int | None,
        decided_at: datetime,
        reason_fa: str | None = None,
        reseller_id: uuid.UUID | None = None,
    ) -> None:
        row = await self._session.get(ResellerApplicationModel, application_id)
        if row is None:
            return
        row.state = state
        row.decided_by = decided_by
        row.decided_at = decided_at
        row.reason_fa = reason_fa
        row.reseller_id = reseller_id
        await self._session.flush()


class SqlAlchemySetupTokens:
    """The hash of a one-time "choose your password" secret, on an admin row."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue(
        self, admin_id: uuid.UUID, *, token_hash: str, expires_at: datetime
    ) -> None:
        row = await self._session.get(AdminModel, admin_id)
        if row is None:
            return
        row.setup_token_hash = token_hash
        row.setup_token_expires_at = expires_at
        await self._session.flush()

    async def find(self, admin_id: uuid.UUID) -> tuple[str, datetime] | None:
        row = await self._session.get(AdminModel, admin_id)
        if row is None or not row.setup_token_hash or row.setup_token_expires_at is None:
            return None
        return row.setup_token_hash, row.setup_token_expires_at

    async def clear(self, admin_id: uuid.UUID) -> None:
        """Called the moment a token is spent.

        A link shared by accident - forwarded, screenshotted - stops working
        once, which is the whole difference between this and a password.
        """
        row = await self._session.get(AdminModel, admin_id)
        if row is None:
            return
        row.setup_token_hash = None
        row.setup_token_expires_at = None
        await self._session.flush()


class SqlAlchemyTopupRepository:
    """Credit requests, with the reseller's name joined in.

    The name rather than only the id: every screen that lists these shows who
    asked, and looking it up per row is how a queue of twenty becomes twenty
    queries.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, **fields: Any) -> uuid.UUID:
        row = ResellerTopupModel(**fields)
        self._session.add(row)
        await self._session.flush()
        return row.id

    async def get(self, topup_id: uuid.UUID) -> TopupView | None:
        stmt = (
            select(ResellerTopupModel, ResellerModel.name_fa)
            .join(ResellerModel, ResellerModel.id == ResellerTopupModel.reseller_id)
            .where(ResellerTopupModel.id == topup_id)
        )
        found = (await self._session.execute(stmt)).first()
        return _topup(*found) if found else None

    async def list_pending(self, *, limit: int = 50) -> Sequence[TopupView]:
        stmt = (
            select(ResellerTopupModel, ResellerModel.name_fa)
            .join(ResellerModel, ResellerModel.id == ResellerTopupModel.reseller_id)
            .where(ResellerTopupModel.state == TOPUP_PENDING)
            # Oldest first: somebody is waiting to be able to sell.
            .order_by(ResellerTopupModel.created_at)
            .limit(limit)
        )
        return [_topup(*row) for row in (await self._session.execute(stmt)).all()]

    async def list_for(
        self, reseller_id: uuid.UUID, *, limit: int = 20
    ) -> Sequence[TopupView]:
        stmt = (
            select(ResellerTopupModel, ResellerModel.name_fa)
            .join(ResellerModel, ResellerModel.id == ResellerTopupModel.reseller_id)
            .where(ResellerTopupModel.reseller_id == reseller_id)
            .order_by(ResellerTopupModel.created_at.desc())
            .limit(limit)
        )
        return [_topup(*row) for row in (await self._session.execute(stmt)).all()]

    async def decide(
        self,
        topup_id: uuid.UUID,
        *,
        state: str,
        decided_by: int | None,
        decided_at: datetime,
        reason_fa: str | None = None,
    ) -> None:
        row = await self._session.get(ResellerTopupModel, topup_id)
        if row is None:
            return
        row.state = state
        row.decided_by = decided_by
        row.decided_at = decided_at
        row.reason_fa = reason_fa
        await self._session.flush()


def _topup(row: ResellerTopupModel, name_fa: str) -> TopupView:
    return TopupView(
        id=row.id,
        reseller_id=row.reseller_id,
        reseller_name_fa=name_fa,
        amount=row.amount,
        note_fa=row.note_fa,
        receipt_file_id=row.receipt_file_id,
        state=row.state,
        created_at=row.created_at,
    )


__all__ = [
    "SqlAlchemyApplicationRepository",
    "SqlAlchemySetupTokens",
    "SqlAlchemyTopupRepository",
]
