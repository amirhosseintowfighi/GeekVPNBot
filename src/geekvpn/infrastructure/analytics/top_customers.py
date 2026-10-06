"""The twenty customers at the top of four different ladders.

Who spent the most, who holds the most live services, who topped up the most
and who has the most sitting in their wallet. Each is a single grouped query:
the bot shows them on demand, and walking every customer through a
repository to sort them in Python would take a busy shop's bot minutes.

Per shop, like every other list an operator sees: the same person in two
shops is two customers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from geekvpn.infrastructure.persistence.models.identity import UserModel
from geekvpn.infrastructure.persistence.models.payments import WalletEntryModel
from geekvpn.infrastructure.persistence.models.provisioning import (
    OrderModel,
    SubscriptionModel,
)

TOP_SIZE = 20
PAID_STATES = ("paid", "provisioning", "active")


class Ladder(StrEnum):
    SPENT = "spent"
    SERVICES = "services"
    TOPPED_UP = "topped_up"
    BALANCE = "balance"


@dataclass(frozen=True, slots=True)
class Rung:
    telegram_id: int
    name: str
    value: int


def _shop(
    column: InstrumentedAttribute[uuid.UUID | None], reseller_id: uuid.UUID | None
) -> ColumnElement[bool]:
    return column.is_(None) if reseller_id is None else column == reseller_id


def _statement(
    ladder: Ladder, *, reseller_id: uuid.UUID | None, now: datetime
) -> Select[int, int]:
    if ladder is Ladder.SPENT:
        value = func.sum(OrderModel.total)
        return (
            select(OrderModel.user_id, value)
            .where(OrderModel.state.in_(PAID_STATES), _shop(OrderModel.reseller_id, reseller_id))
            .group_by(OrderModel.user_id)
            .order_by(value.desc())
        )
    if ladder is Ladder.SERVICES:
        live = func.count()
        return (
            select(SubscriptionModel.user_id, live)
            .where(
                SubscriptionModel.state == "active",
                SubscriptionModel.expires_at > now,
                _shop(SubscriptionModel.reseller_id, reseller_id),
            )
            .group_by(SubscriptionModel.user_id)
            .order_by(live.desc())
        )
    if ladder is Ladder.TOPPED_UP:
        value = func.sum(WalletEntryModel.amount)
        return (
            select(WalletEntryModel.user_id, value)
            .where(
                WalletEntryModel.kind == "topup", _shop(WalletEntryModel.reseller_id, reseller_id)
            )
            .group_by(WalletEntryModel.user_id)
            .order_by(value.desc())
        )
    value = func.sum(WalletEntryModel.amount)
    return (
        select(WalletEntryModel.user_id, value)
        .where(_shop(WalletEntryModel.reseller_id, reseller_id))
        .group_by(WalletEntryModel.user_id)
        .having(value > 0)
        .order_by(value.desc())
    )


def top(
    session: Session,
    ladder: Ladder,
    *,
    now: datetime,
    reseller_id: uuid.UUID | None = None,
    limit: int = TOP_SIZE,
) -> list[Rung]:
    rows = session.execute(_statement(ladder, reseller_id=reseller_id, now=now).limit(limit)).all()
    ids = [int(row[0]) for row in rows]
    names: dict[int, str] = {}
    if ids:
        people = session.execute(
            select(UserModel).where(
                UserModel.telegram_id.in_(ids), _shop(UserModel.reseller_id, reseller_id)
            )
        ).scalars()
        for person in people:
            full = " ".join(part for part in (person.first_name, person.last_name) if part)
            names[person.telegram_id] = (
                person.preferred_name or full or (f"@{person.username}" if person.username else "")
            )
    return [Rung(telegram_id=i, name=names.get(i, ""), value=int(v)) for i, v in rows]


__all__ = ["TOP_SIZE", "Ladder", "Rung", "top"]
