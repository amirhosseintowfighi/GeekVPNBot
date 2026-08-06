"""The composed views: the operator dashboard and the analytics bundle.

The two screens answer different questions and are kept apart on purpose.
The dashboard answers "what needs me now" -- a short action queue. Analytics
answers "how is the business doing" -- trends with comparisons and no verbs.
Merging them produces a screen that is urgent about everything and therefore
about nothing.

The field names here are the wire contract for the admin panel's existing
``AnalyticsBundle`` type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from geekvpn.domain.analytics.enums import MetricKey
from geekvpn.domain.analytics.funnel import Funnel
from geekvpn.domain.analytics.metrics import MetricCard
from geekvpn.domain.analytics.nodes import FleetUsage
from geekvpn.domain.analytics.referral import (
    CampaignPerformance,
    ReferralPerformance,
    ReferrerStanding,
)
from geekvpn.domain.analytics.retention import CohortTable, RetentionSummary
from geekvpn.domain.analytics.revenue import PlanSales, RevenueTotals, TrafficSold
from geekvpn.domain.analytics.segmentation import SegmentReport
from geekvpn.domain.analytics.series import Breakdown, TimeSeries
from geekvpn.domain.analytics.timeframe import DateRange


@dataclass(frozen=True, slots=True)
class ActionItem:
    """One thing an operator should do, with a deep link."""

    key: str
    label_fa: str
    count: int
    href: str
    urgent: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "labelFa": self.label_fa,
            "count": self.count,
            "href": self.href,
            "urgent": self.urgent,
        }


@dataclass(frozen=True, slots=True)
class OperatorDashboard:
    """The landing screen: a queue, not a report."""

    metrics: tuple[MetricCard, ...] = ()
    actions: tuple[ActionItem, ...] = ()
    revenue_series: TimeSeries | None = None
    fleet: FleetUsage | None = None

    def pending_work(self) -> int:
        return sum(item.count for item in self.actions)

    def urgent_actions(self) -> tuple[ActionItem, ...]:
        return tuple(
            sorted(
                (item for item in self.actions if item.count > 0),
                key=lambda item: (not item.urgent, -item.count),
            )
        )

    def is_quiet(self) -> bool:
        """Nothing waiting. The screen should say so rather than show zeros."""
        return self.pending_work() == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "metrics": [card.as_dict() for card in self.metrics],
            "actions": [item.as_dict() for item in self.urgent_actions()],
            "pendingWork": self.pending_work(),
            "quiet": self.is_quiet(),
            "revenueSeries": (self.revenue_series.as_dict() if self.revenue_series else None),
            "fleet": self.fleet.as_dict() if self.fleet else None,
        }


@dataclass(frozen=True, slots=True)
class AnalyticsBundle:
    """Everything the analytics screen renders, in one payload.

    One round trip on purpose: six independent requests would let the cards
    and the charts describe different periods while they load.
    """

    range: DateRange
    revenue: RevenueTotals
    previous_revenue: RevenueTotals = field(default_factory=RevenueTotals)
    retention: RetentionSummary = field(default_factory=RetentionSummary)
    funnel: Funnel = field(default_factory=Funnel)
    referral: ReferralPerformance = field(default_factory=ReferralPerformance)
    segments: SegmentReport = field(default_factory=SegmentReport)
    traffic: TrafficSold = field(default_factory=TrafficSold)
    fleet: FleetUsage = field(default_factory=FleetUsage)
    cohorts: CohortTable = field(default_factory=CohortTable)
    revenue_series: TimeSeries | None = None
    orders_series: TimeSeries | None = None
    plan_breakdown: Breakdown | None = None
    method_breakdown: Breakdown | None = None
    campaigns: tuple[CampaignPerformance, ...] = ()
    top_referrers: tuple[ReferrerStanding, ...] = ()
    top_plans: tuple[PlanSales, ...] = ()

    def metrics(self) -> tuple[MetricCard, ...]:
        """The card row, assembled once so every screen agrees on it."""
        current, before = self.revenue, self.previous_revenue
        return (
            MetricCard.of(MetricKey.NET_REVENUE, current.net, previous=before.net),
            MetricCard.of(MetricKey.ORDERS, current.orders, previous=before.orders),
            MetricCard.of(
                MetricKey.AOV,
                current.average_order_value,
                previous=before.average_order_value,
            ),
            MetricCard.of(MetricKey.NEW_USERS, current.new_users, previous=before.new_users),
            MetricCard.of(MetricKey.CONVERSION, self.funnel.conversion_rate()),
            MetricCard.of(MetricKey.CHURN, self.retention.churn_rate),
            MetricCard.of(MetricKey.RENEWAL_RATE, self.retention.renewal_rate),
            MetricCard.of(MetricKey.TRAFFIC_SOLD, self.traffic.metered_gib),
        )

    def headline_fa(self) -> str:
        return f"{self.range.label_fa()} \u00b7 {self.range.duration_fa()}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "range": {
                "start": self.range.start.isoformat(),
                "end": self.range.end.isoformat(),
                "days": self.range.days,
                "labelFa": self.range.label_fa(),
                "granularity": str(self.range.suggested_granularity()),
            },
            "metrics": [card.as_dict() for card in self.metrics()],
            "revenue": self.revenue.as_dict(),
            "retention": self.retention.as_dict(),
            "funnel": self.funnel.as_dict(),
            "referral": self.referral.as_dict(),
            "segments": self.segments.as_dict(),
            "traffic": self.traffic.as_dict(),
            "fleet": self.fleet.as_dict(),
            "cohorts": self.cohorts.as_dict(),
            "revenueSeries": (self.revenue_series.as_dict() if self.revenue_series else None),
            "ordersSeries": (self.orders_series.as_dict() if self.orders_series else None),
            "planBreakdown": (self.plan_breakdown.as_dict() if self.plan_breakdown else None),
            "methodBreakdown": (self.method_breakdown.as_dict() if self.method_breakdown else None),
            "campaigns": [item.as_dict() for item in self.campaigns],
            "topReferrers": [item.as_dict() for item in self.top_referrers],
            "topPlans": [item.as_dict() for item in self.top_plans],
        }


__all__ = ["ActionItem", "AnalyticsBundle", "OperatorDashboard"]
