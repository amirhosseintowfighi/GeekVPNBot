"""Assembles the analytics bundle.

The service does no arithmetic of its own. It fetches, hands the numbers to
the domain, and returns. Every rate, delta and label is computed in
``domain.analytics`` so the CSV export, the admin screen and a future
Telegram digest cannot disagree about what "net revenue" means.

The previous period is fetched on every call. It doubles the reads, and it is
worth it: a revenue figure with no comparison has never once helped anyone
decide anything.
"""

from __future__ import annotations

from geekvpn.application.analytics.ports import AnalyticsReaders, Clock
from geekvpn.domain.analytics.dashboard import AnalyticsBundle
from geekvpn.domain.analytics.enums import Granularity, MetricFormat, MetricKey
from geekvpn.domain.analytics.funnel import Funnel
from geekvpn.domain.analytics.nodes import FleetUsage
from geekvpn.domain.analytics.referral import leaderboard
from geekvpn.domain.analytics.retention import CohortTable
from geekvpn.domain.analytics.revenue import revenue_by_plan
from geekvpn.domain.analytics.segmentation import SegmentReport
from geekvpn.domain.analytics.series import Breakdown, TimeSeries
from geekvpn.domain.analytics.timeframe import DateRange

DEFAULT_DAYS = 30
COHORT_MONTHS = 6
TOP_PLANS = 5
TOP_REFERRERS = 10

PAYMENT_METHOD_LABELS_FA: dict[str, str] = {
    "wallet": "\u06a9\u06cc\u0641 \u067e\u0648\u0644",
    "card": "\u06a9\u0627\u0631\u062a \u0628\u0647 \u06a9\u0627\u0631\u062a",
    "crypto": "\u0627\u0631\u0632 \u062f\u06cc\u062c\u06cc\u062a\u0627\u0644",
    "gateway": "\u062f\u0631\u06af\u0627\u0647 \u0628\u0627\u0646\u06a9\u06cc",
    "credit": "\u0627\u0639\u062a\u0628\u0627\u0631 \u0647\u062f\u06cc\u0647",
}


class AnalyticsService:
    """Read-only. Nothing here writes, so it can run against a replica."""

    def __init__(self, *, readers: AnalyticsReaders, clock: Clock) -> None:
        self._readers = readers
        self._clock = clock

    # ---- Ranges ---------------------------------------------------------

    def range_for(self, days: int = DEFAULT_DAYS) -> DateRange:
        """Snapped to midnight so "today" is a whole bucket, not a stub."""
        return DateRange.calendar_days(days, now=self._clock.now())

    # ---- The bundle -----------------------------------------------------

    def bundle(self, *, days: int = DEFAULT_DAYS) -> AnalyticsBundle:
        return self.bundle_for(self.range_for(days))

    def bundle_for(self, range: DateRange) -> AnalyticsBundle:
        readers = self._readers
        previous = range.previous()
        granularity = range.suggested_granularity()

        revenue = readers.revenue.totals(range)
        revenue_before = readers.revenue.totals(previous)
        plan_sales = tuple(readers.revenue.plan_sales(range))

        return AnalyticsBundle(
            range=range,
            revenue=revenue,
            previous_revenue=revenue_before,
            retention=readers.retention.summary(range),
            funnel=Funnel.build(readers.funnel.stage_counts(range)),
            referral=readers.referral.performance(range),
            segments=self.segments(),
            traffic=readers.revenue.traffic_sold(range),
            fleet=FleetUsage(nodes=tuple(readers.nodes.usage(range))),
            cohorts=CohortTable(
                cohorts=tuple(
                    readers.retention.cohorts(months=COHORT_MONTHS, now=self._clock.now())
                )
            ),
            revenue_series=self.revenue_series(range, granularity),
            orders_series=self.orders_series(range, granularity),
            plan_breakdown=revenue_by_plan(plan_sales),
            method_breakdown=self.method_breakdown(range),
            campaigns=tuple(readers.campaigns.performance(range)),
            top_referrers=leaderboard(
                tuple(readers.referral.standings(range, limit=TOP_REFERRERS)),
                limit=TOP_REFERRERS,
            ),
            top_plans=tuple(sorted(plan_sales, key=lambda item: item.revenue, reverse=True))[
                :TOP_PLANS
            ],
        )

    # ---- Individual pieces ---------------------------------------------

    def revenue_series(
        self, range: DateRange, granularity: Granularity | None = None
    ) -> TimeSeries:
        return TimeSeries.build(
            key="net_revenue",
            label_fa=MetricKey.NET_REVENUE.label_fa(),
            format=MetricFormat.TOMAN,
            range=range,
            values=self._readers.revenue.net_revenue_by_bucket(range),
            granularity=granularity,
        )

    def orders_series(self, range: DateRange, granularity: Granularity | None = None) -> TimeSeries:
        return TimeSeries.build(
            key="orders",
            label_fa=MetricKey.ORDERS.label_fa(),
            format=MetricFormat.COUNT,
            range=range,
            values=self._readers.revenue.orders_by_bucket(range),
            granularity=granularity,
        )

    def method_breakdown(self, range: DateRange) -> Breakdown:
        rows = self._readers.revenue.revenue_by_method(range)
        return Breakdown.build(
            key="revenue_by_method",
            label_fa="\u062f\u0631\u0622\u0645\u062f \u0628\u0647 \u062a\u0641\u06a9\u06cc\u06a9 \u0631\u0648\u0634 \u067e\u0631\u062f\u0627\u062e\u062a",
            format=MetricFormat.TOMAN,
            rows=rows,
            labels=PAYMENT_METHOD_LABELS_FA,
        )

    def funnel(self, *, days: int = DEFAULT_DAYS) -> Funnel:
        return Funnel.build(self._readers.funnel.stage_counts(self.range_for(days)))

    def segments(self) -> SegmentReport:
        now = self._clock.now()
        return SegmentReport.build(tuple(self._readers.customers.snapshots(now=now)))

    def fleet(self, *, days: int = DEFAULT_DAYS) -> FleetUsage:
        return FleetUsage(nodes=tuple(self._readers.nodes.usage(self.range_for(days))))

    def compare(self, *, days: int = DEFAULT_DAYS) -> tuple[DateRange, DateRange]:
        """The current and previous periods, for a caller that wants both."""
        current = self.range_for(days)
        return current, current.previous()


__all__ = [
    "COHORT_MONTHS",
    "DEFAULT_DAYS",
    "PAYMENT_METHOD_LABELS_FA",
    "TOP_PLANS",
    "TOP_REFERRERS",
    "AnalyticsService",
]
