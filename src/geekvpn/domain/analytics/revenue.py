"""Revenue arithmetic and what was actually sold.

All amounts are whole Toman as plain ``int``. Money values are summed over
thousands of rows here; allocating a value object per row buys nothing, and
the payments context has already guaranteed the invariants.

The distinction that matters: gross is what was invoiced, net is what the
business keeps after discounts and refunds. Reporting one as the other is how
a dashboard tells a comfortable lie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from geekvpn.domain.analytics.enums import MetricFormat, MetricKey
from geekvpn.domain.analytics.metrics import (
    MetricCard,
    fa_number,
    format_value,
    ratio_percent,
    safe_divide,
)
from geekvpn.domain.analytics.series import Breakdown

MIB_PER_GIB = 1024


def gib_from_mib(mib: int | float) -> float:
    return float(mib) / MIB_PER_GIB


@dataclass(frozen=True, slots=True)
class RevenueTotals:
    """Everything the revenue tab needs, from a handful of raw sums."""

    gross: int = 0
    """Invoiced before discounts."""

    discounts: int = 0
    refunds: int = 0
    wallet_topups: int = 0
    orders: int = 0
    paying_users: int = 0
    new_users: int = 0

    @property
    def collected(self) -> int:
        """What customers actually paid."""
        return max(0, self.gross - self.discounts)

    @property
    def net(self) -> int:
        """What the business keeps."""
        return max(0, self.collected - self.refunds)

    @property
    def average_order_value(self) -> float:
        return safe_divide(self.collected, self.orders)

    @property
    def revenue_per_user(self) -> float:
        """ARPU over *paying* users, not over everyone who opened the bot."""
        return safe_divide(self.net, self.paying_users)

    @property
    def discount_rate(self) -> float:
        return ratio_percent(self.discounts, self.gross)

    @property
    def refund_rate(self) -> float:
        return ratio_percent(self.refunds, self.collected)

    def conversion_rate(self, *, visitors: int) -> float:
        return ratio_percent(self.paying_users, visitors)

    def plus(self, other: RevenueTotals) -> RevenueTotals:
        return RevenueTotals(
            gross=self.gross + other.gross,
            discounts=self.discounts + other.discounts,
            refunds=self.refunds + other.refunds,
            wallet_topups=self.wallet_topups + other.wallet_topups,
            orders=self.orders + other.orders,
            paying_users=self.paying_users + other.paying_users,
            new_users=self.new_users + other.new_users,
        )

    def cards(self, previous: RevenueTotals | None = None) -> tuple[MetricCard, ...]:
        """The four headline cards, already compared to the previous period."""
        before = previous or RevenueTotals()
        return (
            MetricCard.of(MetricKey.NET_REVENUE, self.net, previous=before.net),
            MetricCard.of(MetricKey.ORDERS, self.orders, previous=before.orders),
            MetricCard.of(
                MetricKey.AOV,
                self.average_order_value,
                previous=before.average_order_value,
            ),
            MetricCard.of(
                MetricKey.ARPU,
                self.revenue_per_user,
                previous=before.revenue_per_user,
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "gross": self.gross,
            "discounts": self.discounts,
            "refunds": self.refunds,
            "collected": self.collected,
            "net": self.net,
            "walletTopups": self.wallet_topups,
            "orders": self.orders,
            "payingUsers": self.paying_users,
            "newUsers": self.new_users,
            "aov": self.average_order_value,
            "arpu": self.revenue_per_user,
            "discountRate": self.discount_rate,
            "refundRate": self.refund_rate,
            "netFa": format_value(self.net, MetricFormat.TOMAN),
        }


@dataclass(frozen=True, slots=True)
class PlanSales:
    """One product line's contribution."""

    plan_id: str
    plan_name: str
    orders: int = 0
    revenue: int = 0
    traffic_gib: float = 0.0
    days_sold: int = 0

    @property
    def average_price(self) -> float:
        return safe_divide(self.revenue, self.orders)

    def as_dict(self) -> dict[str, Any]:
        return {
            "planId": self.plan_id,
            "planName": self.plan_name,
            "orders": self.orders,
            "revenue": self.revenue,
            "trafficGib": self.traffic_gib,
            "daysSold": self.days_sold,
            "averagePrice": self.average_price,
        }


@dataclass(frozen=True, slots=True)
class TrafficSold:
    """Volume moved, in GiB.

    Unlimited plans are counted separately rather than as a large number:
    folding them in makes "traffic sold" mean whatever the fake cap happens
    to be that month.
    """

    metered_gib: float = 0.0
    unlimited_plans: int = 0
    used_gib: float = 0.0

    @property
    def utilisation(self) -> float:
        """How much of the sold volume customers actually burned."""
        return ratio_percent(self.used_gib, self.metered_gib)

    def summary_fa(self) -> str:
        sold = format_value(self.metered_gib, MetricFormat.GIB)
        if not self.unlimited_plans:
            return sold
        count = fa_number(self.unlimited_plans)
        unlimited = "\u0646\u0627\u0645\u062d\u062f\u0648\u062f"
        plan_word = "\u067e\u0644\u0646"
        return f"{sold} + {count} {plan_word} {unlimited}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "meteredGib": self.metered_gib,
            "unlimitedPlans": self.unlimited_plans,
            "usedGib": self.used_gib,
            "utilisation": self.utilisation,
            "summaryFa": self.summary_fa(),
        }


def revenue_by_plan(sales: tuple[PlanSales, ...]) -> Breakdown:
    return Breakdown.build(
        key="revenue_by_plan",
        label_fa="\u062f\u0631\u0622\u0645\u062f \u0628\u0647 \u062a\u0641\u06a9\u06cc\u06a9 \u067e\u0644\u0646",
        format=MetricFormat.TOMAN,
        rows={item.plan_id: float(item.revenue) for item in sales},
        labels={item.plan_id: item.plan_name for item in sales},
    )


def traffic_by_plan(sales: tuple[PlanSales, ...]) -> Breakdown:
    return Breakdown.build(
        key="traffic_by_plan",
        label_fa="\u062d\u062c\u0645 \u0641\u0631\u0648\u062e\u062a\u0647\u200c\u0634\u062f\u0647 \u0628\u0647 \u062a\u0641\u06a9\u06cc\u06a9 \u067e\u0644\u0646",
        format=MetricFormat.GIB,
        rows={item.plan_id: item.traffic_gib for item in sales},
        labels={item.plan_id: item.plan_name for item in sales},
    )


__all__ = [
    "MIB_PER_GIB",
    "PlanSales",
    "RevenueTotals",
    "TrafficSold",
    "gib_from_mib",
    "revenue_by_plan",
    "traffic_by_plan",
]
