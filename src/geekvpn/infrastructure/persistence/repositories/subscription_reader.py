"""Read side for the reminder sweeps.

Deliberately not the subscription repository. Reminders need a wide, cheap scan
across many customers; the repository exists to be a consistency boundary around
one aggregate. Loading three thousand ``Subscription`` aggregates to ask each one
"how many days left?" would be the expensive way to answer a question SQL can
answer in one pass.

Both queries filter to ACTIVE rows in SQL rather than in Python. The traffic
query additionally excludes unmetered plans (``traffic_limit_mib IS NULL``):
those have no percentage to be over, and including them would mean dividing by
zero in the sweep or - worse - silently treating unlimited as zero.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session

from geekvpn.application.notifications.ports import SubscriptionSnapshot
from geekvpn.domain.provisioning.enums import SubscriptionState
from geekvpn.infrastructure.persistence.models.provisioning import SubscriptionModel

MIB_PER_GIB = 1024

#: Ceiling on one sweep. A sweep that tries to message forty thousand people in
#: one tick will be rate-limited by Telegram and will hold the worker lock for
#: the whole time; the next tick picks up whoever is left.
DEFAULT_LIMIT = 2_000


def _snapshot(row: SubscriptionModel, plan_name: str = "") -> SubscriptionSnapshot:
    total_gib = row.traffic_limit_mib / MIB_PER_GIB if row.traffic_limit_mib else None
    return SubscriptionSnapshot(
        subscription_id=row.id,
        user_id=row.user_id,
        plan_name=plan_name,
        expires_at=row.expires_at,
        used_gib=row.traffic_used_mib / MIB_PER_GIB,
        total_gib=total_gib,
        active=row.state == SubscriptionState.ACTIVE.value,
        last_used_at=row.last_used_at,
        last_connected_at=row.last_connected_at,
        started_at=row.started_at,
    )


class SqlSubscriptionReader:
    """``application.notifications.ports.SubscriptionReader``."""

    def __init__(
        self,
        session: Session,
        *,
        limit: int = DEFAULT_LIMIT,
        reseller_id: uuid.UUID | None = None,
    ) -> None:
        self._session = session
        self._limit = limit
        #: Whose customers this reads. `None` is the platform's own, and it
        #: means exactly that rather than "everybody": a sweep that saw every
        #: shop would warn a reseller's customer through our bot, which the
        #: recipient has never started, so Telegram refuses it and the failure
        #: is recorded as if they had blocked us.
        self._reseller_id = reseller_id

    def _shop(self) -> Any:
        return SubscriptionModel.reseller_id == self._reseller_id

    def expiring_within(self, days: int, *, now: datetime) -> list[SubscriptionSnapshot]:
        """Active subscriptions whose expiry falls inside the window.

        Already-expired rows are included, because the sweep sends a distinct
        "your service has ended" message on the day it dies and needs to see
        that row exactly once.
        """
        horizon = now + timedelta(days=days)
        stmt: Select[Any] = (
            select(SubscriptionModel)
            .where(
                self._shop(),
                SubscriptionModel.state == SubscriptionState.ACTIVE.value,
                SubscriptionModel.expires_at <= horizon,
            )
            .order_by(SubscriptionModel.expires_at)
            .limit(self._limit)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_snapshot(row) for row in rows]

    def with_traffic_usage(
        self, *, min_percent: float, now: datetime
    ) -> list[SubscriptionSnapshot]:
        """Metered subscriptions at or above ``min_percent`` of their cap.

        The comparison happens in SQL so the sweep does not load every metered
        subscription in the system to discard 95% of them.
        """
        ratio = min_percent / 100.0
        stmt: Select[Any] = (
            select(SubscriptionModel)
            .where(
                self._shop(),
                SubscriptionModel.state == SubscriptionState.ACTIVE.value,
                SubscriptionModel.traffic_limit_mib.is_not(None),
                SubscriptionModel.traffic_limit_mib > 0,
                SubscriptionModel.traffic_used_mib >= SubscriptionModel.traffic_limit_mib * ratio,
            )
            .order_by(SubscriptionModel.traffic_used_mib.desc())
            .limit(self._limit)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_snapshot(row) for row in rows]


    def idle_since(self, hours: int, *, now: datetime) -> list[SubscriptionSnapshot]:
        """Live subscriptions the panel has not seen connect for `hours`.

        Measured from `last_connected_at`, which is what the panel itself
        reports. It used to be measured from traffic movement, and that is a
        different question: a counter only grows when bytes flow, and it had
        never been written at all while the usage sweep was broken - so the
        clock fell back to the purchase date and the message went to customers
        who were connecting daily.

        Two populations qualify, and the difference matters:

        * the panel saw them, and that was more than `hours` ago;
        * the panel has never seen them and they have used nothing, since
          buying more than `hours` ago - somebody who could never connect at
          all, which is the most urgent version of this.

        Anyone else is left alone. A customer with traffic on the clock but no
        `last_connected_at` is one whose panel does not report it, and guessing
        at their silence is how the old version got it wrong.
        """
        cutoff = now - timedelta(hours=hours)
        stmt: Select[Any] = (
            select(SubscriptionModel)
            .where(
                self._shop(),
                SubscriptionModel.state == SubscriptionState.ACTIVE.value,
                SubscriptionModel.expires_at > now,
                or_(
                    SubscriptionModel.last_connected_at <= cutoff,
                    and_(
                        SubscriptionModel.last_connected_at.is_(None),
                        SubscriptionModel.traffic_used_mib == 0,
                        SubscriptionModel.started_at <= cutoff,
                    ),
                ),
                # Unmetered plans have no cap to be short of, so `NULL` here has
                # to pass rather than fail the comparison.
                or_(
                    SubscriptionModel.traffic_limit_mib.is_(None),
                    SubscriptionModel.traffic_limit_mib <= 0,
                    SubscriptionModel.traffic_used_mib < SubscriptionModel.traffic_limit_mib,
                ),
            )
            .order_by(
                func.coalesce(SubscriptionModel.last_connected_at, SubscriptionModel.started_at)
            )
            .limit(self._limit)
        )
        rows = self._session.execute(stmt).scalars().all()
        return [_snapshot(row) for row in rows]


__all__ = ["DEFAULT_LIMIT", "SqlSubscriptionReader"]
