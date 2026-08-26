"""Reseller storage.

`save` writes the aggregate whole - the row, its panels and its overrides -
because they are read together and a partial write is how a reseller ends up
priced for panels they cannot reach. The two child tables are replaced rather
than diffed: a handful of rows each, and a diff is more code to get wrong than
it saves.

The bot token is not part of that. It has its own column, its own encryption
context and its own method, so writing the aggregate cannot clear a credential
by omitting it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.resellers.enums import ResellerStatus
from geekvpn.domain.resellers.reseller import PriceOverride, Reseller
from geekvpn.infrastructure.persistence.models.resellers import (
    ResellerLedgerModel,
    ResellerModel,
    ResellerNodeModel,
    ResellerPlanPriceModel,
)


class SqlAlchemyResellerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- reading -----------------------------------------------------------

    async def get(self, reseller_id: uuid.UUID) -> Reseller | None:
        row = await self._session.get(ResellerModel, reseller_id)
        return await self._hydrate(row) if row else None

    async def get_by_admin(self, admin_id: uuid.UUID) -> Reseller | None:
        stmt = select(ResellerModel).where(ResellerModel.admin_id == admin_id)
        row = (await self._session.execute(stmt)).scalars().first()
        return await self._hydrate(row) if row else None

    async def list_all(self) -> Sequence[Reseller]:
        stmt = select(ResellerModel).order_by(ResellerModel.name_fa)
        rows = list((await self._session.execute(stmt)).scalars().all())
        return [await self._hydrate(row) for row in rows]

    async def _hydrate(self, row: ResellerModel) -> Reseller:
        nodes = (
            await self._session.execute(
                select(ResellerNodeModel.node_id).where(
                    ResellerNodeModel.reseller_id == row.id
                )
            )
        ).scalars().all()
        prices = (
            await self._session.execute(
                select(ResellerPlanPriceModel).where(
                    ResellerPlanPriceModel.reseller_id == row.id
                )
            )
        ).scalars().all()

        return Reseller(
            id=row.id,
            admin_id=row.admin_id,
            name_fa=row.name_fa,
            status=ResellerStatus(row.status),
            discount_percent=row.discount_percent,
            balance_amount=row.balance,
            allowed_node_ids=frozenset(nodes),
            overrides=tuple(
                PriceOverride(
                    plan_id=row_price.plan_id,
                    cost=None if row_price.price is None else Money(row_price.price),
                    retail=(
                        None
                        if row_price.retail_price is None
                        else Money(row_price.retail_price)
                    ),
                )
                for row_price in prices
            ),
            contact_fa=row.contact_fa,
        )

    # -- writing -----------------------------------------------------------

    async def add(self, reseller: Reseller) -> None:
        self._session.add(
            ResellerModel(
                id=reseller.id,
                admin_id=reseller.admin_id,
                name_fa=reseller.name_fa,
                status=reseller.status.value,
                discount_percent=reseller.discount_percent,
                balance=reseller.balance_amount,
                contact_fa=reseller.contact_fa,
            )
        )
        await self._session.flush()
        await self._write_children(reseller)

    async def save(self, reseller: Reseller) -> None:
        row = await self._session.get(ResellerModel, reseller.id)
        if row is None:
            await self.add(reseller)
            return
        row.name_fa = reseller.name_fa
        row.status = reseller.status.value
        row.discount_percent = reseller.discount_percent
        row.balance = reseller.balance_amount
        row.contact_fa = reseller.contact_fa
        await self._write_children(reseller)

    async def _write_children(self, reseller: Reseller) -> None:
        await self._session.execute(
            delete(ResellerNodeModel).where(ResellerNodeModel.reseller_id == reseller.id)
        )
        for node_id in sorted(reseller.allowed_node_ids):
            self._session.add(
                ResellerNodeModel(reseller_id=reseller.id, node_id=node_id)
            )

        await self._session.execute(
            delete(ResellerPlanPriceModel).where(
                ResellerPlanPriceModel.reseller_id == reseller.id
            )
        )
        for override in reseller.overrides:
            # A row with neither number is a row that says nothing. It would
            # round-trip as an override that changes no price, which is worse
            # than absent because it looks deliberate on the screen.
            if override.cost is None and override.retail is None:
                continue
            self._session.add(
                ResellerPlanPriceModel(
                    reseller_id=reseller.id,
                    plan_id=override.plan_id,
                    price=None if override.cost is None else override.cost.amount,
                    retail_price=(
                        None if override.retail is None else override.retail.amount
                    ),
                )
            )
        await self._session.flush()

    # -- credit ledger -----------------------------------------------------

    async def record(
        self,
        *,
        reseller_id: uuid.UUID,
        entry_id: str,
        amount: int,
        balance_after: int,
        kind: str,
        description_fa: str,
        occurred_at: datetime,
        reference: str | None = None,
        actor_id: int | None = None,
    ) -> None:
        self._session.add(
            ResellerLedgerModel(
                id=entry_id,
                reseller_id=reseller_id,
                amount=amount,
                balance_after=balance_after,
                kind=kind,
                description_fa=description_fa,
                reference=reference,
                actor_id=actor_id,
                occurred_at=occurred_at,
            )
        )
        await self._session.flush()

    async def history(
        self, reseller_id: uuid.UUID, *, limit: int = 50
    ) -> Sequence[ResellerLedgerModel]:
        stmt = (
            select(ResellerLedgerModel)
            .where(ResellerLedgerModel.reseller_id == reseller_id)
            .order_by(ResellerLedgerModel.occurred_at.desc())
            .limit(limit)
        )
        return list((await self._session.execute(stmt)).scalars().all())

    # -- the reseller's own bot -------------------------------------------

    async def set_bot(
        self, reseller_id: uuid.UUID, *, token: str | None, username: str | None
    ) -> None:
        row = await self._session.get(ResellerModel, reseller_id)
        if row is None:
            return
        row.bot_token_encrypted = token
        row.bot_username = username
        await self._session.flush()

    async def bot_token(self, reseller_id: uuid.UUID) -> str | None:
        row = await self._session.get(ResellerModel, reseller_id)
        return row.bot_token_encrypted if row else None

    async def with_bots(self) -> Sequence[tuple[uuid.UUID, str, str | None]]:
        """Every active reseller that has a bot to run.

        Read at start-up by whatever process serves the webhooks. Active only:
        a suspended reseller's bot must stop answering, and the cheapest way to
        stop it is to never register it.
        """
        stmt = select(ResellerModel).where(
            ResellerModel.status == ResellerStatus.ACTIVE.value,
            ResellerModel.bot_token_encrypted.is_not(None),
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [
            (row.id, row.bot_token_encrypted or "", row.bot_username) for row in rows
        ]


__all__ = ["SqlAlchemyResellerRepository"]
