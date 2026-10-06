"""Who is owed the newcomer gift: joined in the window, never bought, never had it.

One query rather than a walk over the customers: the worker asks every hour,
and the answer is usually nobody.

"Bought" is any order that took money or is taking it - paid, being
delivered, delivered - and not a free trial: someone who only tried the
service is exactly who the gift is for.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, exists, select
from sqlalchemy.orm import Session

from geekvpn.application.payments.newcomer_gift import REFERENCE
from geekvpn.domain.identity.enums import UserStatus
from geekvpn.domain.provisioning.enums import OrderSource, OrderState
from geekvpn.infrastructure.persistence.models.identity import UserModel
from geekvpn.infrastructure.persistence.models.payments import WalletEntryModel
from geekvpn.infrastructure.persistence.models.provisioning import OrderModel

_BOUGHT = (
    OrderState.PAID.value,
    OrderState.PROVISIONING.value,
    OrderState.ACTIVE.value,
    OrderState.FAILED.value,
)
#: A big shop's first evening after switching the gift on is still bounded.
BATCH = 500


def newcomers_without_purchase(
    session: Session, joined_after: datetime, joined_before: datetime
) -> list[int]:
    bought = exists().where(
        and_(
            OrderModel.user_id == UserModel.telegram_id,
            OrderModel.reseller_id.is_(None),
            OrderModel.state.in_(_BOUGHT),
            OrderModel.source != OrderSource.TRIAL.value,
        )
    )
    gifted = exists().where(
        and_(
            WalletEntryModel.user_id == UserModel.telegram_id,
            WalletEntryModel.reseller_id.is_(None),
            WalletEntryModel.reference == REFERENCE,
        )
    )
    rows = session.execute(
        select(UserModel.telegram_id)
        .where(
            UserModel.reseller_id.is_(None),
            UserModel.status == UserStatus.ACTIVE.value,
            UserModel.created_at >= joined_after,
            UserModel.created_at < joined_before,
            ~bought,
            ~gifted,
        )
        .order_by(UserModel.created_at)
        .limit(BATCH)
    ).scalars()
    return [int(telegram_id) for telegram_id in rows]


__all__ = ["BATCH", "newcomers_without_purchase"]
