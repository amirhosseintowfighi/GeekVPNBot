"""SQL behind a reseller's charts (`application/resellers/trade`).

Every query here is filtered by the one reseller id first. The platform's own
readers are scoped to nothing, and a reseller must never be pointed at them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from geekvpn.application.resellers.service import ADJUSTMENT, SALE, TOPUP
from geekvpn.application.resellers.trade import ResellerTotals, ResellerTrade
from geekvpn.domain.analytics.enums import MetricFormat
from geekvpn.domain.analytics.series import BreakdownSlice, TimeSeries
from geekvpn.domain.analytics.timeframe import DateRange
from geekvpn.domain.provisioning.enums import OrderState, SubscriptionState
from geekvpn.infrastructure.persistence.models.identity import UserModel
from geekvpn.infrastructure.persistence.models.provisioning import OrderModel, SubscriptionModel
from geekvpn.infrastructure.persistence.models.resellers import ResellerLedgerModel

#: Paid and kept, as the daily report counts it.
_TAKEN = (
    OrderState.PAID.value,
    OrderState.PROVISIONING.value,
    OrderState.ACTIVE.value,
    OrderState.FAILED.value,
)
TOP_PLANS = 6


def _buckets(rows: Iterable[tuple[datetime, float]], period: DateRange) -> dict[datetime, float]:
    """Rows snapped onto the period's buckets; days without a row stay zero."""
    buckets = dict.fromkeys(period.buckets(), 0.0)
    for at, value in rows:
        bucket = period.bucket_of(at)
        if bucket in buckets:
            buckets[bucket] += float(value)
    return buckets


class SqlResellerTradeReader:
    """Implements ``ResellerTradeReader``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def trade(self, reseller_id: uuid.UUID, period: DateRange) -> ResellerTrade:
        ledger = ResellerLedgerModel
        sales = (
            await self._session.execute(
                select(ledger.occurred_at, ledger.amount).where(
                    ledger.reseller_id == reseller_id,
                    ledger.kind == SALE,
                    ledger.occurred_at >= period.start,
                    ledger.occurred_at < period.end,
                )
            )
        ).all()
        paid = (
            await self._session.execute(
                select(OrderModel.paid_at, OrderModel.total, OrderModel.plan_name_fa).where(
                    OrderModel.reseller_id == reseller_id,
                    OrderModel.state.in_(_TAKEN),
                    OrderModel.paid_at >= period.start,
                    OrderModel.paid_at < period.end,
                )
            )
        ).all()

        def series(
            key: str, label_fa: str, fmt: MetricFormat, values: dict[datetime, float]
        ) -> TimeSeries:
            return TimeSeries.build(
                key=key, label_fa=label_fa, format=fmt, range=period, values=values
            )

        by_plan: dict[str, int] = {}
        for _, _, plan_name in paid:
            by_plan[plan_name] = by_plan.get(plan_name, 0) + 1
        sold = sum(by_plan.values())
        top = sorted(by_plan.items(), key=lambda item: item[1], reverse=True)[:TOP_PLANS]

        async def count(stmt: object) -> int:
            return int((await self._session.execute(stmt)).scalar_one())  # type: ignore[call-overload]

        return ResellerTrade(
            sales=series(
                "sales",
                "تعداد فروش",
                MetricFormat.COUNT,
                _buckets(((at, 1) for at, _ in sales), period),
            ),
            cost=series(
                "cost",
                "هزینهٔ خرید از ما",
                MetricFormat.TOMAN,
                _buckets(((at, -amount) for at, amount in sales), period),
            ),
            revenue=series(
                "revenue",
                "پرداخت مشتری‌ها در ربات",
                MetricFormat.TOMAN,
                _buckets(((at, total) for at, total, _ in paid if at is not None), period),
            ),
            top_plans=tuple(
                BreakdownSlice(
                    key=name, label_fa=name, value=float(n), share=(n * 100 / sold) if sold else 0.0
                )
                for name, n in top
            ),
            new_customers=await count(
                select(func.count())
                .select_from(UserModel)
                .where(
                    UserModel.reseller_id == reseller_id,
                    UserModel.created_at >= period.start,
                    UserModel.created_at < period.end,
                )
            ),
            customers=await count(
                select(func.count())
                .select_from(UserModel)
                .where(UserModel.reseller_id == reseller_id)
            ),
            active_services=await count(
                select(func.count())
                .select_from(SubscriptionModel)
                .where(
                    SubscriptionModel.reseller_id == reseller_id,
                    SubscriptionModel.state == SubscriptionState.ACTIVE.value,
                )
            ),
        )

    async def totals(self, reseller_id: uuid.UUID) -> ResellerTotals:
        ledger = ResellerLedgerModel
        is_sale = ledger.kind == SALE
        is_topup = ledger.kind.in_((TOPUP, ADJUSTMENT)) & (ledger.amount > 0)
        row = (
            await self._session.execute(
                select(
                    func.count(case((is_sale, 1))),
                    func.coalesce(func.sum(case((is_sale, -ledger.amount), else_=0)), 0),
                    func.coalesce(func.sum(case((is_topup, ledger.amount), else_=0)), 0),
                ).where(ledger.reseller_id == reseller_id)
            )
        ).one()
        return ResellerTotals(sales=int(row[0]), spent=int(row[1]), topped_up=int(row[2]))
