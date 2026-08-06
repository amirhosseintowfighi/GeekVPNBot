"""Customer segmentation.

A segment is a *rule*, evaluated against a customer snapshot, not a stored
list. Stored lists rot: a "win back" list built on Saturday still contains
people who renewed on Sunday, and mailing them a discount for something they
already bought is worse than saying nothing.

Evaluation is deliberately ordered and returns a single primary segment,
because a customer can only be targeted by one campaign at a time without
feeling harassed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from geekvpn.domain.analytics.calendar import fa_digits
from geekvpn.domain.analytics.enums import MetricFormat, SegmentKind
from geekvpn.domain.analytics.metrics import ratio_percent
from geekvpn.domain.analytics.retention import (
    AT_RISK_DAYS,
    CHURN_GRACE_DAYS,
    is_churned,
)
from geekvpn.domain.analytics.series import Breakdown

NEW_CUSTOMER_DAYS = 14
DORMANT_DAYS = 60
LOYAL_MIN_ORDERS = 3
WHALE_MIN_SPEND = 3_000_000
"""Toman. Matches the gold loyalty tier so the two never disagree."""

REFERRER_MIN_CONVERTED = 1


@dataclass(frozen=True, slots=True)
class CustomerSnapshot:
    """Everything segmentation is allowed to look at.

    A flat snapshot rather than a live aggregate: segmentation runs over tens
    of thousands of rows and must never pull a subscription graph per user.
    """

    user_id: int
    joined_days_ago: int = 0
    orders: int = 0
    lifetime_spend: int = 0
    days_to_expiry: int | None = None
    """Negative once expired. None when the customer has no subscription."""

    days_since_last_order: int | None = None
    referrals_converted: int = 0
    has_active_subscription: bool = False

    @property
    def days_since_expiry(self) -> int:
        if self.days_to_expiry is None or self.days_to_expiry > 0:
            return 0
        return -self.days_to_expiry

    @property
    def is_buyer(self) -> bool:
        return self.orders > 0


def classify(snapshot: CustomerSnapshot) -> SegmentKind:
    """The single most useful label for one customer.

    Order matters and encodes priority: an expiring whale is shown as
    \u062f\u0631 \u0622\u0633\u062a\u0627\u0646\u0647\u0654 \u0627\u0646\u0642\u0636\u0627 because that is the fact worth acting on today.
    """
    if not snapshot.is_buyer:
        return SegmentKind.NEVER_PURCHASED

    if (
        snapshot.has_active_subscription
        and snapshot.days_to_expiry is not None
        and 0 <= snapshot.days_to_expiry <= AT_RISK_DAYS
    ):
        return SegmentKind.EXPIRING_SOON

    if not snapshot.has_active_subscription and snapshot.days_to_expiry is not None:
        if is_churned(snapshot.days_since_expiry):
            return SegmentKind.CHURNED
        if snapshot.days_since_expiry > 0:
            return SegmentKind.EXPIRED

    if snapshot.joined_days_ago <= NEW_CUSTOMER_DAYS:
        return SegmentKind.NEW

    last_order = snapshot.days_since_last_order
    if last_order is not None and last_order >= DORMANT_DAYS:
        return SegmentKind.DORMANT

    if snapshot.lifetime_spend >= WHALE_MIN_SPEND:
        return SegmentKind.WHALE
    if snapshot.orders >= LOYAL_MIN_ORDERS:
        return SegmentKind.LOYAL
    if snapshot.referrals_converted >= REFERRER_MIN_CONVERTED:
        return SegmentKind.REFERRER
    if snapshot.has_active_subscription:
        return SegmentKind.ACTIVE
    return SegmentKind.AT_RISK


def matches(snapshot: CustomerSnapshot, kind: SegmentKind) -> bool:
    """Membership test that allows overlap.

    ``classify`` picks one label for display; targeting sometimes wants
    "every whale", including the ones currently about to expire.
    """
    if kind is SegmentKind.WHALE:
        return snapshot.lifetime_spend >= WHALE_MIN_SPEND
    if kind is SegmentKind.LOYAL:
        return snapshot.orders >= LOYAL_MIN_ORDERS
    if kind is SegmentKind.REFERRER:
        return snapshot.referrals_converted >= REFERRER_MIN_CONVERTED
    if kind is SegmentKind.ACTIVE:
        return snapshot.has_active_subscription
    if kind is SegmentKind.NEVER_PURCHASED:
        return not snapshot.is_buyer
    return classify(snapshot) is kind


@dataclass(frozen=True, slots=True)
class SegmentStat:
    """One segment's size and worth."""

    kind: SegmentKind
    customers: int = 0
    revenue: int = 0
    share: float = 0.0

    @property
    def label_fa(self) -> str:
        return self.kind.label_fa()

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": str(self.kind),
            "labelFa": self.label_fa,
            "customers": self.customers,
            "revenue": self.revenue,
            "share": self.share,
            "isWinBack": self.kind.is_win_back(),
        }


@dataclass(frozen=True, slots=True)
class SegmentReport:
    """The whole customer base, sliced."""

    stats: tuple[SegmentStat, ...] = ()

    @classmethod
    def build(cls, snapshots: tuple[CustomerSnapshot, ...]) -> SegmentReport:
        counts: dict[SegmentKind, int] = {}
        revenue: dict[SegmentKind, int] = {}
        for snapshot in snapshots:
            kind = classify(snapshot)
            counts[kind] = counts.get(kind, 0) + 1
            revenue[kind] = revenue.get(kind, 0) + snapshot.lifetime_spend

        total = len(snapshots)
        stats = tuple(
            SegmentStat(
                kind=kind,
                customers=counts[kind],
                revenue=revenue.get(kind, 0),
                share=ratio_percent(counts[kind], total),
            )
            for kind in sorted(counts, key=lambda k: counts[k], reverse=True)
        )
        return cls(stats=stats)

    @property
    def total_customers(self) -> int:
        return sum(stat.customers for stat in self.stats)

    def stat_for(self, kind: SegmentKind) -> SegmentStat:
        for stat in self.stats:
            if stat.kind is kind:
                return stat
        return SegmentStat(kind=kind)

    def win_back_audience(self) -> int:
        return sum(stat.customers for stat in self.stats if stat.kind.is_win_back())

    def headline_fa(self) -> str:
        return (
            f"{fa_digits(self.win_back_audience())} "
            "\u0645\u0634\u062a\u0631\u06cc \u0642\u0627\u0628\u0644 \u0628\u0627\u0632\u06af\u0631\u062f\u0627\u0646\u062f\u0646"
        )

    def to_breakdown(self) -> Breakdown:
        return Breakdown.build(
            key="segments",
            label_fa="\u0628\u062e\u0634\u200c\u0628\u0646\u062f\u06cc \u0645\u0634\u062a\u0631\u06cc\u0627\u0646",
            format=MetricFormat.COUNT,
            rows={str(stat.kind): float(stat.customers) for stat in self.stats},
            labels={str(stat.kind): stat.label_fa for stat in self.stats},
            top_n=len(self.stats) or 1,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "totalCustomers": self.total_customers,
            "winBackAudience": self.win_back_audience(),
            "stats": [stat.as_dict() for stat in self.stats],
        }


__all__ = [
    "CHURN_GRACE_DAYS",
    "DORMANT_DAYS",
    "LOYAL_MIN_ORDERS",
    "NEW_CUSTOMER_DAYS",
    "WHALE_MIN_SPEND",
    "CustomerSnapshot",
    "SegmentReport",
    "SegmentStat",
    "classify",
    "matches",
]
