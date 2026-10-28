"""SQL behind the daily orders report (`application/analytics/daily_report`)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import ColumnElement, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.analytics.daily_report import DayOrders
from geekvpn.domain.provisioning.enums import OrderState
from geekvpn.infrastructure.persistence.models.identity import UserModel
from geekvpn.infrastructure.persistence.models.provisioning import OrderModel

_WAITING = (OrderState.PAID.value, OrderState.PROVISIONING.value)
_UNPAID = (OrderState.PENDING.value, OrderState.CANCELLED.value)
#: Paid and kept: what the day actually took in.
_TAKEN = (
    OrderState.PAID.value,
    OrderState.PROVISIONING.value,
    OrderState.ACTIVE.value,
    OrderState.FAILED.value,
)


class SqlDayOrdersReader:
    """Implements ``DayOrdersReader``. Every shop's orders, resellers' included:
    the report is the owner's view of the whole platform."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def day(self, day: date, *, start: datetime, end: datetime) -> DayOrders:
        def count(condition: ColumnElement[bool]) -> ColumnElement[int]:
            return func.count(case((condition, 1)))

        state = OrderModel.state
        placed_row = (
            await self._session.execute(
                select(
                    func.count(),
                    count(state == OrderState.ACTIVE.value),
                    count(state.in_(_WAITING)),
                    count(state == OrderState.FAILED.value),
                    count(state.in_(_UNPAID)),
                    count(state == OrderState.REFUNDED.value),
                ).where(OrderModel.placed_at >= start, OrderModel.placed_at < end)
            )
        ).one()
        # By the day the money arrived, which for a card transfer reviewed
        # the next morning is not the day the order was placed.
        paid_today = and_(OrderModel.paid_at >= start, OrderModel.paid_at < end, state.in_(_TAKEN))
        paid_row = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(OrderModel.total), 0),
                    count(OrderModel.is_renewal.is_(True)),
                ).where(paid_today)
            )
        ).one()
        new_customers = (
            await self._session.execute(
                select(func.count())
                .select_from(UserModel)
                .where(UserModel.created_at >= start, UserModel.created_at < end)
            )
        ).scalar_one()

        placed, delivered, waiting, failed, unpaid, refunded = (int(v) for v in placed_row)
        return DayOrders(
            day=day,
            placed=placed,
            delivered=delivered,
            waiting=waiting,
            failed=failed,
            unpaid=unpaid,
            refunded=refunded,
            revenue=int(paid_row[0]),
            renewals=int(paid_row[1]),
            new_customers=int(new_customers),
        )
