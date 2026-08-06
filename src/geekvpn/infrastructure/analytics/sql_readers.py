"""SQL implementations of the analytics reader ports.

Why these are synchronous while the rest of the platform is async: the ports
say so, and they say so for a reason. Every method here is one aggregate query
against an indexed column, run from the admin panel or a nightly export -- never
from the customer hot path. A synchronous read-only session keeps analytics off
the request event loop entirely, so a slow report cannot stall the bot.

The rules these queries follow:

* **Aggregate in the database.** Nothing here loads rows to sum them in Python.
  The one exception is customer snapshots, which are deliberately capped.
* **Half-open ranges.** ``placed_at >= start AND placed_at < end``, matching
  ``DateRange``. ``BETWEEN`` would double-count the boundary between two
  adjacent periods.
* **Settlement time, not row age.** Revenue is sliced by ``paid_at``. An order
  created in Tir and paid in Mordad is Mordad's revenue.
* **Zero-filled buckets.** The query returns only the days that had sales; the
  reader fills the rest, because a chart that skips empty days draws a smooth
  line through an outage.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Float, and_, case, cast, distinct, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import ColumnElement, Select

from geekvpn.domain.analytics.calendar import jalali_month_label
from geekvpn.domain.analytics.enums import FunnelStage
from geekvpn.domain.analytics.nodes import NodeUsage
from geekvpn.domain.analytics.referral import (
    CampaignPerformance,
    ReferralPerformance,
    ReferrerStanding,
)
from geekvpn.domain.analytics.retention import Cohort, RetentionSummary
from geekvpn.domain.analytics.revenue import PlanSales, RevenueTotals, TrafficSold, gib_from_mib
from geekvpn.domain.analytics.segmentation import CustomerSnapshot
from geekvpn.domain.analytics.timeframe import DateRange
from geekvpn.domain.payments.enums import PaymentState, TransactionKind
from geekvpn.infrastructure.persistence.models.catalog import CampaignModel
from geekvpn.infrastructure.persistence.models.identity import UserModel
from geekvpn.infrastructure.persistence.models.payments import (
    PaymentModel,
    RefundModel,
    WalletEntryModel,
)
from geekvpn.infrastructure.persistence.models.provisioning import (
    FunnelEventModel,
    NodeModel,
    OrderModel,
    ReferralModel,
    SubscriptionModel,
)
from geekvpn.infrastructure.persistence.models.support import TicketModel

#: Orders that represent money we actually kept.
SETTLED_ORDER_STATES = ("paid", "provisioning", "active")
#: Everything that was ever paid for, including money later returned. Refunds
#: are subtracted separately rather than by dropping the order, so that a
#: refunded sale still appears in gross revenue where it belongs.
PAID_ORDER_STATES = (*SETTLED_ORDER_STATES, "refunded")

MONTH_KEY_FORMAT = "%Y-%m"


def _zero_filled(rows: Iterable[tuple[datetime, float]], range: DateRange) -> dict[datetime, float]:
    """Snap query rows onto the range's buckets and fill the gaps with zero."""
    buckets = dict.fromkeys(range.buckets(), 0.0)
    for at, value in rows:
        if at is None:
            continue
        bucket = range.bucket_of(at)
        if bucket in buckets:
            buckets[bucket] += float(value or 0)
    return buckets


class SqlRevenueReader:
    """Money, in whole Toman."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _paid_in(self, range: DateRange) -> ColumnElement[bool]:
        return and_(
            OrderModel.paid_at.is_not(None),
            OrderModel.paid_at >= range.start,
            OrderModel.paid_at < range.end,
            OrderModel.state.in_(PAID_ORDER_STATES),
        )

    def totals(self, range: DateRange) -> RevenueTotals:
        row = self._session.execute(
            select(
                func.coalesce(func.sum(OrderModel.total), 0),
                func.coalesce(func.sum(OrderModel.discount), 0),
                func.count(OrderModel.id),
                func.count(distinct(OrderModel.user_id)),
            ).where(self._paid_in(range))
        ).one()
        gross, discounts, orders, paying_users = row

        refunds = self._session.execute(
            select(func.coalesce(func.sum(RefundModel.amount), 0)).where(
                RefundModel.refunded_at >= range.start,
                RefundModel.refunded_at < range.end,
            )
        ).scalar_one()

        # Top-ups are money received, not revenue earned. They are reported
        # beside revenue, never inside it: crediting a wallet and then selling
        # from that wallet would otherwise count the same Toman twice.
        topups = self._session.execute(
            select(func.coalesce(func.sum(WalletEntryModel.amount), 0)).where(
                WalletEntryModel.kind == TransactionKind.TOPUP.value,
                WalletEntryModel.occurred_at >= range.start,
                WalletEntryModel.occurred_at < range.end,
            )
        ).scalar_one()

        new_users = self._session.execute(
            select(func.count(UserModel.id)).where(
                UserModel.created_at >= range.start,
                UserModel.created_at < range.end,
            )
        ).scalar_one()

        return RevenueTotals(
            gross=int(gross),
            discounts=int(discounts),
            refunds=int(refunds),
            wallet_topups=int(topups),
            orders=int(orders),
            paying_users=int(paying_users),
            new_users=int(new_users),
        )

    def net_revenue_by_bucket(self, range: DateRange) -> dict[datetime, float]:
        rows = self._session.execute(
            select(OrderModel.paid_at, OrderModel.total).where(self._paid_in(range))
        ).all()
        buckets = _zero_filled(((at, float(total)) for at, total in rows), range)

        # Refunds land in the bucket they were issued in, not the bucket of the
        # original sale. Rewriting history would make yesterday's published
        # chart change overnight.
        refunds = self._session.execute(
            select(RefundModel.refunded_at, RefundModel.amount).where(
                RefundModel.refunded_at >= range.start,
                RefundModel.refunded_at < range.end,
            )
        ).all()
        for at, amount in refunds:
            bucket = range.bucket_of(at)
            if bucket in buckets:
                buckets[bucket] -= float(amount)
        return buckets

    def orders_by_bucket(self, range: DateRange) -> dict[datetime, float]:
        rows = self._session.execute(
            select(OrderModel.paid_at, func.count(OrderModel.id))
            .where(self._paid_in(range))
            .group_by(OrderModel.paid_at)
        ).all()
        return _zero_filled(((at, float(count)) for at, count in rows), range)

    def plan_sales(self, range: DateRange) -> list[PlanSales]:
        rows = self._session.execute(
            select(
                OrderModel.plan_id,
                func.min(OrderModel.plan_name_fa),
                func.count(OrderModel.id),
                func.coalesce(func.sum(OrderModel.total), 0),
                func.coalesce(func.sum(OrderModel.traffic_mib), 0),
                func.coalesce(func.sum(OrderModel.duration_days), 0),
            )
            .where(self._paid_in(range))
            .group_by(OrderModel.plan_id)
            .order_by(func.coalesce(func.sum(OrderModel.total), 0).desc())
        ).all()
        return [
            PlanSales(
                plan_id=str(plan_id),
                plan_name=name or str(plan_id),
                orders=int(orders),
                revenue=int(revenue),
                traffic_gib=gib_from_mib(int(traffic_mib)),
                days_sold=int(days),
            )
            for plan_id, name, orders, revenue, traffic_mib, days in rows
        ]

    def revenue_by_method(self, range: DateRange) -> dict[str, float]:
        rows = self._session.execute(
            select(
                PaymentModel.method,
                func.coalesce(func.sum(PaymentModel.captured), 0),
            )
            .where(
                PaymentModel.settled_at.is_not(None),
                PaymentModel.settled_at >= range.start,
                PaymentModel.settled_at < range.end,
                PaymentModel.state.in_(
                    (
                        PaymentState.APPROVED.value,
                        PaymentState.PARTIALLY_REFUNDED.value,
                        PaymentState.REFUNDED.value,
                    )
                ),
            )
            .group_by(PaymentModel.method)
        ).all()
        return {str(method): float(total) for method, total in rows}

    def traffic_sold(self, range: DateRange) -> TrafficSold:
        metered_mib, unlimited = self._session.execute(
            select(
                func.coalesce(
                    func.sum(
                        case((OrderModel.traffic_mib.is_not(None), OrderModel.traffic_mib), else_=0)
                    ),
                    0,
                ),
                func.count(case((OrderModel.traffic_mib.is_(None), 1))),
            ).where(self._paid_in(range))
        ).one()

        # Consumption is a property of live subscriptions, not of orders, so it
        # is read from the subscription rows the range's orders produced.
        used_mib = self._session.execute(
            select(func.coalesce(func.sum(SubscriptionModel.traffic_used_mib), 0)).where(
                SubscriptionModel.started_at >= range.start,
                SubscriptionModel.started_at < range.end,
            )
        ).scalar_one()

        return TrafficSold(
            metered_gib=gib_from_mib(int(metered_mib)),
            unlimited_plans=int(unlimited),
            used_gib=gib_from_mib(int(used_mib)),
        )


class SqlFunnelReader:
    """Distinct users reaching each stage.

    Distinct users, not events: a customer who opens the shop nine times is one
    person deciding, not nine.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def stage_counts(self, range: DateRange) -> dict[FunnelStage, int]:
        rows = self._session.execute(
            select(
                FunnelEventModel.stage,
                func.count(distinct(FunnelEventModel.user_id)),
            )
            .where(
                FunnelEventModel.occurred_at >= range.start,
                FunnelEventModel.occurred_at < range.end,
            )
            .group_by(FunnelEventModel.stage)
        ).all()
        counted = {str(stage): int(count) for stage, count in rows}
        return {stage: counted.get(stage.value, 0) for stage in FunnelStage}


class SqlRetentionReader:
    def __init__(self, session: Session) -> None:
        self._session = session

    def summary(self, range: DateRange) -> RetentionSummary:
        active_start = self._active_at(range.start)
        active_end = self._active_at(range.end)

        expired = self._session.execute(
            select(func.count(SubscriptionModel.id)).where(
                SubscriptionModel.expires_at >= range.start,
                SubscriptionModel.expires_at < range.end,
            )
        ).scalar_one()

        renewed = self._session.execute(
            select(func.count(OrderModel.id)).where(
                OrderModel.is_renewal.is_(True),
                OrderModel.paid_at.is_not(None),
                OrderModel.paid_at >= range.start,
                OrderModel.paid_at < range.end,
                OrderModel.state.in_(PAID_ORDER_STATES),
            )
        ).scalar_one()

        # Churn is expiry that stayed expired past the grace period. Somebody
        # who lapsed yesterday has not churned; they have not renewed yet.
        churned = max(int(expired) - int(renewed), 0)

        new_customers = self._session.execute(
            select(func.count(distinct(OrderModel.user_id))).where(
                OrderModel.is_renewal.is_(False),
                OrderModel.paid_at.is_not(None),
                OrderModel.paid_at >= range.start,
                OrderModel.paid_at < range.end,
                OrderModel.state.in_(PAID_ORDER_STATES),
            )
        ).scalar_one()

        net_revenue = self._session.execute(
            select(func.coalesce(func.sum(OrderModel.total), 0)).where(
                OrderModel.paid_at.is_not(None),
                OrderModel.paid_at >= range.start,
                OrderModel.paid_at < range.end,
                OrderModel.state.in_(SETTLED_ORDER_STATES),
            )
        ).scalar_one()

        lifetime_days = self._session.execute(
            select(func.coalesce(func.avg(cast(OrderModel.duration_days, Float)), 0.0)).where(
                self._paid_window(range)
            )
        ).scalar_one()

        return RetentionSummary(
            active_start=int(active_start),
            active_end=int(active_end),
            expired=int(expired),
            renewed=int(renewed),
            churned=churned,
            new_customers=int(new_customers),
            net_revenue=int(net_revenue),
            lifetime_months=round(float(lifetime_days) / 30.0, 2),
        )

    def _paid_window(self, range: DateRange) -> ColumnElement[bool]:
        return and_(
            OrderModel.paid_at.is_not(None),
            OrderModel.paid_at >= range.start,
            OrderModel.paid_at < range.end,
            OrderModel.state.in_(PAID_ORDER_STATES),
        )

    def _active_at(self, moment: datetime) -> int:
        """Subscriptions that were live at a point in time.

        Reconstructed from the dates rather than from ``state``, because the
        state column describes now, and "now" is not when the report starts.
        """
        return int(
            self._session.execute(
                select(func.count(distinct(SubscriptionModel.user_id))).where(
                    SubscriptionModel.started_at <= moment,
                    SubscriptionModel.expires_at > moment,
                    SubscriptionModel.state != "revoked",
                )
            ).scalar_one()
        )

    def cohorts(self, *, months: int, now: datetime) -> list[Cohort]:
        """Monthly acquisition cohorts and their renewal behaviour."""
        first_day = (now - timedelta(days=30 * months)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        rows = self._session.execute(
            select(
                OrderModel.user_id,
                func.min(OrderModel.paid_at),
            )
            .where(
                OrderModel.paid_at.is_not(None),
                OrderModel.paid_at >= first_day,
                OrderModel.state.in_(PAID_ORDER_STATES),
            )
            .group_by(OrderModel.user_id)
        ).all()

        members: dict[str, list[tuple[int, datetime]]] = {}
        for user_id, first_paid in rows:
            key = first_paid.strftime(MONTH_KEY_FORMAT)
            members.setdefault(key, []).append((int(user_id), first_paid))

        cohorts: list[Cohort] = []
        for key in sorted(members):
            people = members[key]
            user_ids = [user_id for user_id, _ in people]
            anchor = min(first_paid for _, first_paid in people)
            periods = max(int((now - anchor).days // 30), 0) + 1
            retained: list[int] = []
            for period in range(periods):
                window_start = anchor + timedelta(days=30 * period)
                window_end = window_start + timedelta(days=30)
                if period == 0:
                    retained.append(len(user_ids))
                    continue
                still_here = self._session.execute(
                    select(func.count(distinct(OrderModel.user_id))).where(
                        OrderModel.user_id.in_(user_ids),
                        OrderModel.paid_at >= window_start,
                        OrderModel.paid_at < window_end,
                        OrderModel.state.in_(PAID_ORDER_STATES),
                    )
                ).scalar_one()
                retained.append(int(still_here))
            cohorts.append(
                Cohort.build(
                    key=key,
                    label_fa=jalali_month_label(anchor),
                    size=len(user_ids),
                    retained=tuple(retained),
                )
            )
        return cohorts


class SqlReferralReader:
    def __init__(self, session: Session) -> None:
        self._session = session

    def performance(self, range: DateRange) -> ReferralPerformance:
        signups, rewards, bonuses, revenue, referrers = self._session.execute(
            select(
                func.count(ReferralModel.id),
                func.coalesce(func.sum(ReferralModel.reward_paid), 0),
                func.coalesce(func.sum(ReferralModel.invitee_bonus_paid), 0),
                func.coalesce(func.sum(ReferralModel.revenue_generated), 0),
                func.count(distinct(ReferralModel.referrer_id)),
            ).where(
                ReferralModel.joined_at >= range.start,
                ReferralModel.joined_at < range.end,
            )
        ).one()

        converted = self._session.execute(
            select(func.count(ReferralModel.id)).where(
                ReferralModel.converted_at.is_not(None),
                ReferralModel.converted_at >= range.start,
                ReferralModel.converted_at < range.end,
            )
        ).scalar_one()

        return ReferralPerformance(
            signups=int(signups),
            converted=int(converted),
            revenue=int(revenue),
            rewards_paid=int(rewards),
            invitee_bonuses=int(bonuses),
            active_referrers=int(referrers),
        )

    def standings(self, range: DateRange, *, limit: int = 10) -> list[ReferrerStanding]:
        rows = self._session.execute(
            select(
                ReferralModel.referrer_id,
                func.count(ReferralModel.id),
                func.count(ReferralModel.converted_at),
                func.coalesce(func.sum(ReferralModel.revenue_generated), 0),
                func.coalesce(func.sum(ReferralModel.reward_paid), 0),
                # UserModel has no display_name; Telegram gives us a first
                # name, sometimes a username, sometimes neither.
                func.min(func.coalesce(UserModel.first_name, UserModel.username)),
            )
            .join(UserModel, UserModel.telegram_id == ReferralModel.referrer_id, isouter=True)
            .where(
                ReferralModel.joined_at >= range.start,
                ReferralModel.joined_at < range.end,
            )
            .group_by(ReferralModel.referrer_id)
            .order_by(func.coalesce(func.sum(ReferralModel.revenue_generated), 0).desc())
            .limit(limit)
        ).all()
        return [
            ReferrerStanding(
                user_id=int(referrer_id),
                display_name=name or str(referrer_id),
                invited=int(invited),
                converted=int(converted),
                revenue=int(revenue),
                reward_paid=int(reward),
            )
            for referrer_id, invited, converted, revenue, reward, name in rows
        ]


class SqlCampaignAnalyticsReader:
    def __init__(self, session: Session) -> None:
        self._session = session

    def performance(self, range: DateRange) -> list[CampaignPerformance]:
        rows = self._session.execute(
            select(
                OrderModel.campaign_id,
                func.min(CampaignModel.name_fa),
                func.min(CampaignModel.kind),
                func.count(OrderModel.id),
                func.coalesce(func.sum(OrderModel.total), 0),
                func.coalesce(func.sum(OrderModel.discount), 0),
                func.count(case((OrderModel.is_renewal.is_(False), 1))),
            )
            .join(CampaignModel, CampaignModel.id == OrderModel.campaign_id, isouter=True)
            .where(
                OrderModel.campaign_id.is_not(None),
                OrderModel.paid_at.is_not(None),
                OrderModel.paid_at >= range.start,
                OrderModel.paid_at < range.end,
                OrderModel.state.in_(PAID_ORDER_STATES),
            )
            .group_by(OrderModel.campaign_id)
            .order_by(func.coalesce(func.sum(OrderModel.total), 0).desc())
        ).all()
        return [
            CampaignPerformance(
                campaign_id=str(campaign_id),
                name_fa=name or str(campaign_id),
                kind=str(kind or ""),
                redemptions=int(orders),
                orders=int(orders),
                gross_revenue=int(revenue),
                discount_given=int(discount),
                new_customers=int(new_customers),
            )
            for campaign_id, name, kind, orders, revenue, discount, new_customers in rows
        ]


class SqlNodeReader:
    def __init__(self, session: Session) -> None:
        self._session = session

    def usage(self, range: DateRange) -> list[NodeUsage]:
        rows = self._session.execute(
            select(
                NodeModel.id,
                NodeModel.name_fa,
                NodeModel.country_code,
                NodeModel.state,
                NodeModel.capacity,
                NodeModel.account_count,
                NodeModel.traffic_used_mib,
            )
            .where(NodeModel.state != "retired")
            .order_by(NodeModel.sort_order, NodeModel.name_fa)
        ).all()
        return [
            NodeUsage(
                node_id=str(node_id),
                name=name,
                country_fa=country or "",
                online=state in ("online", "degraded"),
                accounts=int(accounts),
                capacity=int(capacity),
                traffic_gib=gib_from_mib(int(traffic_mib)),
            )
            for node_id, name, country, state, capacity, accounts, traffic_mib in rows
        ]


class SqlCustomerReader:
    """Flat snapshots for segmentation and gamification.

    This is the one place that returns rows instead of totals, because
    segmentation is a per-customer rule set. The limit is real: past it, the
    report is a batch job, not a page load.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def _base_query(self, now: datetime) -> Select[Any]:
        newest_expiry = func.max(SubscriptionModel.expires_at)
        return (
            select(
                UserModel.telegram_id,
                UserModel.created_at,
                func.count(distinct(OrderModel.id)),
                func.coalesce(func.sum(OrderModel.total), 0),
                func.max(OrderModel.paid_at),
                newest_expiry,
                func.count(distinct(ReferralModel.id)),
            )
            .join(
                OrderModel,
                and_(
                    OrderModel.user_id == UserModel.telegram_id,
                    OrderModel.state.in_(PAID_ORDER_STATES),
                    OrderModel.paid_at.is_not(None),
                ),
                isouter=True,
            )
            .join(
                SubscriptionModel,
                and_(
                    SubscriptionModel.user_id == UserModel.telegram_id,
                    SubscriptionModel.state != "revoked",
                ),
                isouter=True,
            )
            .join(
                ReferralModel,
                and_(
                    ReferralModel.referrer_id == UserModel.telegram_id,
                    ReferralModel.converted_at.is_not(None),
                ),
                isouter=True,
            )
            .group_by(UserModel.telegram_id, UserModel.created_at)
        )

    @staticmethod
    def _to_snapshot(row: tuple, now: datetime) -> CustomerSnapshot:
        (
            user_id,
            joined_at,
            orders,
            spend,
            last_paid,
            expires_at,
            referrals,
        ) = row
        days_to_expiry = None
        if expires_at is not None:
            days_to_expiry = (expires_at - now).days
        days_since_last_order = None
        if last_paid is not None:
            days_since_last_order = max((now - last_paid).days, 0)
        return CustomerSnapshot(
            user_id=int(user_id),
            joined_days_ago=max((now - joined_at).days, 0) if joined_at else 0,
            orders=int(orders or 0),
            lifetime_spend=int(spend or 0),
            days_to_expiry=days_to_expiry,
            days_since_last_order=days_since_last_order,
            referrals_converted=int(referrals or 0),
            has_active_subscription=days_to_expiry is not None and days_to_expiry >= 0,
        )

    def snapshots(self, *, now: datetime, limit: int = 50_000) -> list[CustomerSnapshot]:
        rows = self._session.execute(self._base_query(now).limit(limit)).all()
        return [self._to_snapshot(row, now) for row in rows]

    def snapshot_for(self, user_id: int, *, now: datetime) -> CustomerSnapshot | None:
        row = self._session.execute(
            self._base_query(now).having(UserModel.telegram_id == user_id)
        ).first()
        return self._to_snapshot(row, now) if row is not None else None


class SqlWorkQueueReader:
    """What is waiting for a human right now. Deliberately not date-ranged."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def pending(self, *, now: datetime) -> Any:
        from geekvpn.application.analytics.ports import WorkQueue

        pending_payments = self._session.execute(
            select(func.count(PaymentModel.id)).where(
                PaymentModel.state == PaymentState.PENDING_REVIEW.value
            )
        ).scalar_one()

        open_tickets = self._session.execute(
            select(func.count(TicketModel.id)).where(
                TicketModel.state.in_(("open", "waiting_user", "answered"))
            )
        ).scalar_one()

        # Overdue means the SLA for its priority has already elapsed while the
        # ticket was waiting on us.
        overdue = self._session.execute(
            select(func.count(TicketModel.id)).where(
                TicketModel.state == "open",
                TicketModel.waiting_since.is_not(None),
                or_(
                    and_(
                        TicketModel.priority == "urgent",
                        TicketModel.waiting_since < now - timedelta(minutes=30),
                    ),
                    and_(
                        TicketModel.priority == "high",
                        TicketModel.waiting_since < now - timedelta(minutes=120),
                    ),
                    and_(
                        TicketModel.priority == "normal",
                        TicketModel.waiting_since < now - timedelta(minutes=480),
                    ),
                    and_(
                        TicketModel.priority == "low",
                        TicketModel.waiting_since < now - timedelta(minutes=1440),
                    ),
                ),
            )
        ).scalar_one()

        failed_provisions = self._session.execute(
            select(func.count(OrderModel.id)).where(OrderModel.state == "failed")
        ).scalar_one()

        end_of_day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        expiring_today = self._session.execute(
            select(func.count(SubscriptionModel.id)).where(
                SubscriptionModel.state == "active",
                SubscriptionModel.expires_at >= now,
                SubscriptionModel.expires_at < end_of_day,
            )
        ).scalar_one()

        return WorkQueue(
            pending_payments=int(pending_payments),
            open_tickets=int(open_tickets),
            overdue_tickets=int(overdue),
            failed_provisions=int(failed_provisions),
            expiring_today=int(expiring_today),
        )


def build_readers(session: Session) -> Any:
    """Assemble the whole reader bag from one session."""
    from geekvpn.application.analytics.ports import AnalyticsReaders

    return AnalyticsReaders(
        revenue=SqlRevenueReader(session),
        funnel=SqlFunnelReader(session),
        retention=SqlRetentionReader(session),
        referral=SqlReferralReader(session),
        campaigns=SqlCampaignAnalyticsReader(session),
        nodes=SqlNodeReader(session),
        customers=SqlCustomerReader(session),
        work_queue=SqlWorkQueueReader(session),
    )


__all__ = [
    "PAID_ORDER_STATES",
    "SETTLED_ORDER_STATES",
    "SqlCampaignAnalyticsReader",
    "SqlCustomerReader",
    "SqlFunnelReader",
    "SqlNodeReader",
    "SqlReferralReader",
    "SqlRetentionReader",
    "SqlRevenueReader",
    "SqlWorkQueueReader",
    "build_readers",
]
