"""Who took the free trial in a window and has bought nothing since, per shop.

Read from the trial *orders* rather than the claims: a claim records only who
and when, and the follow-up has to go out through the shop the trial was
taken in. Test accounts a reseller made from their console are filed under a
negative owner id and are not anybody's chat.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, and_, exists, select
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased

from geekvpn.domain.provisioning.enums import OrderSource, OrderState
from geekvpn.infrastructure.persistence.models.provisioning import OrderModel

_BOUGHT = (
    OrderState.PAID.value,
    OrderState.PROVISIONING.value,
    OrderState.ACTIVE.value,
    OrderState.FAILED.value,
)
BATCH = 500


def trial_takers_without_purchase(
    session: Session, reseller_id: uuid.UUID | None, after: datetime, before: datetime
) -> list[int]:
    trial = aliased(OrderModel)
    purchase = aliased(OrderModel)

    def shop(column: InstrumentedAttribute[uuid.UUID | None]) -> ColumnElement[bool]:
        return column.is_(None) if reseller_id is None else column == reseller_id

    bought = exists().where(
        and_(
            purchase.user_id == trial.user_id,
            shop(purchase.reseller_id),
            purchase.source != OrderSource.TRIAL.value,
            purchase.state.in_(_BOUGHT),
        )
    )
    rows = session.execute(
        select(trial.user_id)
        .where(
            trial.source == OrderSource.TRIAL.value,
            shop(trial.reseller_id),
            trial.user_id > 0,
            trial.placed_at >= after,
            trial.placed_at < before,
            ~bought,
        )
        .group_by(trial.user_id)
        .order_by(trial.user_id)
        .limit(BATCH)
    ).scalars()
    return [int(user_id) for user_id in rows]


__all__ = ["BATCH", "trial_takers_without_purchase"]
