"""Referral and campaign performance.

Both answer the same uncomfortable question: did this cost more than it
brought in? So both carry the reward or discount they consumed alongside the
revenue they produced, and both can report a negative return.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from geekvpn.domain.analytics.enums import MetricFormat
from geekvpn.domain.analytics.metrics import ratio_percent, safe_divide
from geekvpn.domain.analytics.series import Breakdown


@dataclass(frozen=True, slots=True)
class ReferrerStanding:
    """One inviter's record, for the leaderboard."""

    user_id: int
    display_name: str
    invited: int = 0
    converted: int = 0
    revenue: int = 0
    reward_paid: int = 0

    @property
    def conversion_rate(self) -> float:
        return ratio_percent(self.converted, self.invited)

    @property
    def net_contribution(self) -> int:
        return self.revenue - self.reward_paid

    def as_dict(self) -> dict[str, Any]:
        return {
            "userId": self.user_id,
            "displayName": self.display_name,
            "invited": self.invited,
            "converted": self.converted,
            "revenue": self.revenue,
            "rewardPaid": self.reward_paid,
            "conversionRate": self.conversion_rate,
            "netContribution": self.net_contribution,
        }


@dataclass(frozen=True, slots=True)
class ReferralPerformance:
    """The referral programme as a whole."""

    signups: int = 0
    converted: int = 0
    revenue: int = 0
    rewards_paid: int = 0
    invitee_bonuses: int = 0
    active_referrers: int = 0

    @property
    def conversion_rate(self) -> float:
        return ratio_percent(self.converted, self.signups)

    @property
    def total_cost(self) -> int:
        return self.rewards_paid + self.invitee_bonuses

    @property
    def net_revenue(self) -> int:
        return self.revenue - self.total_cost

    @property
    def cost_per_acquisition(self) -> float:
        return safe_divide(self.total_cost, self.converted)

    @property
    def return_on_spend(self) -> float:
        """Revenue per Toman of reward, as a percentage."""
        return ratio_percent(self.revenue, self.total_cost)

    def is_profitable(self) -> bool:
        return self.net_revenue > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "signups": self.signups,
            "converted": self.converted,
            "revenue": self.revenue,
            "rewardsPaid": self.rewards_paid,
            "inviteeBonuses": self.invitee_bonuses,
            "activeReferrers": self.active_referrers,
            "conversionRate": self.conversion_rate,
            "totalCost": self.total_cost,
            "netRevenue": self.net_revenue,
            "cpa": self.cost_per_acquisition,
            "roas": self.return_on_spend,
            "profitable": self.is_profitable(),
        }


@dataclass(frozen=True, slots=True)
class CampaignPerformance:
    """One campaign or coupon, judged on incremental revenue."""

    campaign_id: str
    name_fa: str
    kind: str = ""
    impressions: int = 0
    redemptions: int = 0
    orders: int = 0
    gross_revenue: int = 0
    discount_given: int = 0
    new_customers: int = 0

    @property
    def net_revenue(self) -> int:
        return max(0, self.gross_revenue - self.discount_given)

    @property
    def redemption_rate(self) -> float:
        return ratio_percent(self.redemptions, self.impressions)

    @property
    def average_order_value(self) -> float:
        return safe_divide(self.net_revenue, self.orders)

    @property
    def discount_rate(self) -> float:
        return ratio_percent(self.discount_given, self.gross_revenue)

    @property
    def new_customer_share(self) -> float:
        return ratio_percent(self.new_customers, self.orders)

    def return_on_discount(self) -> float:
        """Net revenue per Toman of discount, as a percentage.

        A campaign under 100 here gave away more than it earned back.
        """
        return ratio_percent(self.net_revenue, self.discount_given)

    def as_dict(self) -> dict[str, Any]:
        return {
            "campaignId": self.campaign_id,
            "nameFa": self.name_fa,
            "kind": self.kind,
            "impressions": self.impressions,
            "redemptions": self.redemptions,
            "orders": self.orders,
            "grossRevenue": self.gross_revenue,
            "discountGiven": self.discount_given,
            "netRevenue": self.net_revenue,
            "redemptionRate": self.redemption_rate,
            "discountRate": self.discount_rate,
            "newCustomerShare": self.new_customer_share,
            "returnOnDiscount": self.return_on_discount(),
        }


def campaign_breakdown(rows: tuple[CampaignPerformance, ...]) -> Breakdown:
    return Breakdown.build(
        key="campaign_revenue",
        label_fa="\u062f\u0631\u0622\u0645\u062f \u06a9\u0645\u067e\u06cc\u0646\u200c\u0647\u0627",
        format=MetricFormat.TOMAN,
        rows={item.campaign_id: float(item.net_revenue) for item in rows},
        labels={item.campaign_id: item.name_fa for item in rows},
    )


def leaderboard(
    standings: tuple[ReferrerStanding, ...], *, limit: int = 10
) -> tuple[ReferrerStanding, ...]:
    """Rank by revenue produced, not by invitations sent.

    Ranking on raw invites rewards spamming; ranking on revenue rewards
    inviting people who actually want the product.
    """
    return tuple(sorted(standings, key=lambda item: (item.revenue, item.converted), reverse=True))[
        :limit
    ]


__all__ = [
    "CampaignPerformance",
    "ReferralPerformance",
    "ReferrerStanding",
    "campaign_breakdown",
    "leaderboard",
]
