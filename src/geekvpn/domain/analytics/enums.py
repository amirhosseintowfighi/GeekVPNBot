"""Vocabulary for the analytics context.

Every enum carries a Persian label because these values reach the admin panel
directly. Formats are declared here rather than in the UI so a number is never
rendered as Toman in one screen and a bare count in another.
"""

from __future__ import annotations

import enum


class Granularity(enum.StrEnum):
    """Bucket size for a time series."""

    DAY = "day"
    WEEK = "week"
    MONTH = "month"

    def label_fa(self) -> str:
        return {
            Granularity.DAY: "\u0631\u0648\u0632\u0627\u0646\u0647",
            Granularity.WEEK: "\u0647\u0641\u062a\u06af\u06cc",
            Granularity.MONTH: "\u0645\u0627\u0647\u0627\u0646\u0647",
        }[self]

    def approximate_days(self) -> int:
        return {Granularity.DAY: 1, Granularity.WEEK: 7, Granularity.MONTH: 30}[self]


class MetricFormat(enum.StrEnum):
    """How a raw number becomes a string.

    Mirrors the admin panel's ``MetricCard['format']`` union exactly.
    """

    TOMAN = "toman"
    COUNT = "count"
    PERCENT = "percent"
    GIB = "gib"
    DAYS = "days"

    def label_fa(self) -> str:
        return {
            MetricFormat.TOMAN: "\u062a\u0648\u0645\u0627\u0646",
            MetricFormat.COUNT: "\u062a\u0639\u062f\u0627\u062f",
            MetricFormat.PERCENT: "\u062f\u0631\u0635\u062f",
            MetricFormat.GIB: "\u06af\u06cc\u06af\u0627\u0628\u0627\u06cc\u062a",
            MetricFormat.DAYS: "\u0631\u0648\u0632",
        }[self]


class MetricKey(enum.StrEnum):
    """The metrics the business actually steers by.

    Deliberately finite. An open string key invites two screens to compute
    "revenue" two different ways and then argue about which is right.
    """

    GROSS_REVENUE = "gross_revenue"
    NET_REVENUE = "net_revenue"
    REFUNDS = "refunds"
    DISCOUNTS = "discounts"
    ORDERS = "orders"
    AOV = "aov"
    ARPU = "arpu"
    LTV = "ltv"
    NEW_USERS = "new_users"
    PAYING_USERS = "paying_users"
    ACTIVE_SUBSCRIPTIONS = "active_subscriptions"
    CONVERSION = "conversion"
    CHURN = "churn"
    RENEWAL_RATE = "renewal_rate"
    TRAFFIC_SOLD = "traffic_sold"
    TRAFFIC_USED = "traffic_used"
    WALLET_TOPUP = "wallet_topup"
    REFERRAL_REVENUE = "referral_revenue"
    REFERRAL_SIGNUPS = "referral_signups"
    CAMPAIGN_REVENUE = "campaign_revenue"

    def label_fa(self) -> str:
        return _METRIC_LABELS[self]

    def format(self) -> MetricFormat:
        return _METRIC_FORMATS[self]

    def lower_is_better(self) -> bool:
        """Churn going up is bad news painted green unless we say so."""
        return self in (MetricKey.CHURN, MetricKey.REFUNDS)


_METRIC_LABELS: dict[MetricKey, str] = {
    MetricKey.GROSS_REVENUE: "\u062f\u0631\u0622\u0645\u062f \u0646\u0627\u062e\u0627\u0644\u0635",
    MetricKey.NET_REVENUE: "\u062f\u0631\u0622\u0645\u062f \u062e\u0627\u0644\u0635",
    MetricKey.REFUNDS: "\u0627\u0633\u062a\u0631\u062f\u0627\u062f",
    MetricKey.DISCOUNTS: "\u062a\u062e\u0641\u06cc\u0641\u200c\u0647\u0627",
    MetricKey.ORDERS: "\u0633\u0641\u0627\u0631\u0634\u200c\u0647\u0627",
    MetricKey.AOV: "\u0645\u06cc\u0627\u0646\u06af\u06cc\u0646 \u0627\u0631\u0632\u0634 \u0633\u0641\u0627\u0631\u0634",
    MetricKey.ARPU: "\u062f\u0631\u0622\u0645\u062f \u0628\u0647 \u0627\u0632\u0627\u06cc \u0647\u0631 \u06a9\u0627\u0631\u0628\u0631",
    MetricKey.LTV: "\u0627\u0631\u0632\u0634 \u0637\u0648\u0644 \u0639\u0645\u0631 \u0645\u0634\u062a\u0631\u06cc",
    MetricKey.NEW_USERS: "\u06a9\u0627\u0631\u0628\u0631\u0627\u0646 \u062c\u062f\u06cc\u062f",
    MetricKey.PAYING_USERS: "\u062e\u0631\u06cc\u062f\u0627\u0631\u0627\u0646",
    MetricKey.ACTIVE_SUBSCRIPTIONS: "\u0627\u0634\u062a\u0631\u0627\u06a9\u200c\u0647\u0627\u06cc \u0641\u0639\u0627\u0644",
    MetricKey.CONVERSION: "\u0646\u0631\u062e \u062a\u0628\u062f\u06cc\u0644",
    MetricKey.CHURN: "\u0646\u0631\u062e \u0631\u06cc\u0632\u0634",
    MetricKey.RENEWAL_RATE: "\u0646\u0631\u062e \u062a\u0645\u062f\u06cc\u062f",
    MetricKey.TRAFFIC_SOLD: "\u062d\u062c\u0645 \u0641\u0631\u0648\u062e\u062a\u0647\u200c\u0634\u062f\u0647",
    MetricKey.TRAFFIC_USED: "\u062d\u062c\u0645 \u0645\u0635\u0631\u0641\u200c\u0634\u062f\u0647",
    MetricKey.WALLET_TOPUP: "\u0634\u0627\u0631\u0698 \u06a9\u06cc\u0641 \u067e\u0648\u0644",
    MetricKey.REFERRAL_REVENUE: "\u062f\u0631\u0622\u0645\u062f \u0645\u0639\u0631\u0641\u06cc",
    MetricKey.REFERRAL_SIGNUPS: "\u062b\u0628\u062a\u200c\u0646\u0627\u0645 \u0628\u0627 \u0645\u0639\u0631\u0641\u06cc",
    MetricKey.CAMPAIGN_REVENUE: "\u062f\u0631\u0622\u0645\u062f \u06a9\u0645\u067e\u06cc\u0646",
}

_T = MetricFormat
_METRIC_FORMATS: dict[MetricKey, MetricFormat] = {
    MetricKey.GROSS_REVENUE: _T.TOMAN,
    MetricKey.NET_REVENUE: _T.TOMAN,
    MetricKey.REFUNDS: _T.TOMAN,
    MetricKey.DISCOUNTS: _T.TOMAN,
    MetricKey.ORDERS: _T.COUNT,
    MetricKey.AOV: _T.TOMAN,
    MetricKey.ARPU: _T.TOMAN,
    MetricKey.LTV: _T.TOMAN,
    MetricKey.NEW_USERS: _T.COUNT,
    MetricKey.PAYING_USERS: _T.COUNT,
    MetricKey.ACTIVE_SUBSCRIPTIONS: _T.COUNT,
    MetricKey.CONVERSION: _T.PERCENT,
    MetricKey.CHURN: _T.PERCENT,
    MetricKey.RENEWAL_RATE: _T.PERCENT,
    MetricKey.TRAFFIC_SOLD: _T.GIB,
    MetricKey.TRAFFIC_USED: _T.GIB,
    MetricKey.WALLET_TOPUP: _T.TOMAN,
    MetricKey.REFERRAL_REVENUE: _T.TOMAN,
    MetricKey.REFERRAL_SIGNUPS: _T.COUNT,
    MetricKey.CAMPAIGN_REVENUE: _T.TOMAN,
}


class TrendDirection(enum.StrEnum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"

    def label_fa(self) -> str:
        return {
            TrendDirection.UP: "\u0635\u0639\u0648\u062f\u06cc",
            TrendDirection.DOWN: "\u0646\u0632\u0648\u0644\u06cc",
            TrendDirection.FLAT: "\u0628\u062f\u0648\u0646 \u062a\u063a\u06cc\u06cc\u0631",
        }[self]


class FunnelStage(enum.StrEnum):
    """The purchase funnel, in order.

    Stops at PROVISIONED rather than at approval: money cleared is not the
    same as a working VPN, and the gap between those two stages is the most
    expensive one in the whole product.
    """

    STARTED = "started"
    VIEWED_SHOP = "viewed_shop"
    SELECTED_PLAN = "selected_plan"
    INVOICE_CREATED = "invoice_created"
    PROOF_SUBMITTED = "proof_submitted"
    PAYMENT_APPROVED = "payment_approved"
    PROVISIONED = "provisioned"

    def label_fa(self) -> str:
        return {
            FunnelStage.STARTED: "\u0634\u0631\u0648\u0639 \u0631\u0628\u0627\u062a",
            FunnelStage.VIEWED_SHOP: "\u0645\u0634\u0627\u0647\u062f\u0647\u0654 \u0641\u0631\u0648\u0634\u06af\u0627\u0647",
            FunnelStage.SELECTED_PLAN: "\u0627\u0646\u062a\u062e\u0627\u0628 \u067e\u0644\u0646",
            FunnelStage.INVOICE_CREATED: "\u0635\u062f\u0648\u0631 \u0641\u0627\u06a9\u062a\u0648\u0631",
            FunnelStage.PROOF_SUBMITTED: "\u0627\u0631\u0633\u0627\u0644 \u0631\u0633\u06cc\u062f",
            FunnelStage.PAYMENT_APPROVED: "\u062a\u0623\u06cc\u06cc\u062f \u067e\u0631\u062f\u0627\u062e\u062a",
            FunnelStage.PROVISIONED: "\u062a\u062d\u0648\u06cc\u0644 \u0633\u0631\u0648\u06cc\u0633",
        }[self]

    @classmethod
    def ordered(cls) -> tuple[FunnelStage, ...]:
        return (
            cls.STARTED,
            cls.VIEWED_SHOP,
            cls.SELECTED_PLAN,
            cls.INVOICE_CREATED,
            cls.PROOF_SUBMITTED,
            cls.PAYMENT_APPROVED,
            cls.PROVISIONED,
        )

    def position(self) -> int:
        return FunnelStage.ordered().index(self)


class SegmentKind(enum.StrEnum):
    """Who a customer is right now, for targeting."""

    NEW = "new"
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    CHURNED = "churned"
    AT_RISK = "at_risk"
    LOYAL = "loyal"
    WHALE = "whale"
    DORMANT = "dormant"
    NEVER_PURCHASED = "never_purchased"
    REFERRER = "referrer"

    def label_fa(self) -> str:
        return {
            SegmentKind.NEW: "\u062a\u0627\u0632\u0647\u200c\u0648\u0627\u0631\u062f",
            SegmentKind.ACTIVE: "\u0641\u0639\u0627\u0644",
            SegmentKind.EXPIRING_SOON: "\u062f\u0631 \u0622\u0633\u062a\u0627\u0646\u0647\u0654 \u0627\u0646\u0642\u0636\u0627",
            SegmentKind.EXPIRED: "\u0645\u0646\u0642\u0636\u06cc\u200c\u0634\u062f\u0647",
            SegmentKind.CHURNED: "\u0631\u06cc\u0632\u0634\u200c\u06a9\u0631\u062f\u0647",
            SegmentKind.AT_RISK: "\u062f\u0631 \u062e\u0637\u0631 \u0631\u06cc\u0632\u0634",
            SegmentKind.LOYAL: "\u0648\u0641\u0627\u062f\u0627\u0631",
            SegmentKind.WHALE: "\u067e\u0631\u062e\u0631\u06cc\u062f",
            SegmentKind.DORMANT: "\u062e\u0627\u0645\u0648\u0634",
            SegmentKind.NEVER_PURCHASED: "\u0628\u062f\u0648\u0646 \u062e\u0631\u06cc\u062f",
            SegmentKind.REFERRER: "\u0645\u0639\u0631\u0641\u200c\u06a9\u0646\u0646\u062f\u0647",
        }[self]

    def is_win_back(self) -> bool:
        """Segments a discount campaign should target rather than annoy."""
        return self in (
            SegmentKind.EXPIRED,
            SegmentKind.CHURNED,
            SegmentKind.AT_RISK,
            SegmentKind.DORMANT,
        )


class BadgeKind(enum.StrEnum):
    """Gamification badges. Cosmetic by design -- see gamification.py."""

    FIRST_PURCHASE = "first_purchase"
    RENEWED_THRICE = "renewed_thrice"
    HALF_YEAR = "half_year"
    FULL_YEAR = "full_year"
    BIG_SPENDER = "big_spender"
    REFERRER_ROOKIE = "referrer_rookie"
    REFERRER_PRO = "referrer_pro"
    EARLY_ADOPTER = "early_adopter"

    def label_fa(self) -> str:
        return {
            BadgeKind.FIRST_PURCHASE: "\u0627\u0648\u0644\u06cc\u0646 \u062e\u0631\u06cc\u062f",
            BadgeKind.RENEWED_THRICE: "\u0633\u0647 \u0628\u0627\u0631 \u062a\u0645\u062f\u06cc\u062f",
            BadgeKind.HALF_YEAR: "\u0634\u0634 \u0645\u0627\u0647 \u0647\u0645\u0631\u0627\u0647",
            BadgeKind.FULL_YEAR: "\u06cc\u06a9 \u0633\u0627\u0644 \u0647\u0645\u0631\u0627\u0647",
            BadgeKind.BIG_SPENDER: "\u0645\u0634\u062a\u0631\u06cc \u0648\u06cc\u0698\u0647",
            BadgeKind.REFERRER_ROOKIE: "\u0645\u0639\u0631\u0641 \u062a\u0627\u0632\u0647\u200c\u06a9\u0627\u0631",
            BadgeKind.REFERRER_PRO: "\u0645\u0639\u0631\u0641 \u062d\u0631\u0641\u0647\u200c\u0627\u06cc",
            BadgeKind.EARLY_ADOPTER: "\u0647\u0645\u0631\u0627\u0647 \u0646\u062e\u0633\u062a\u06cc\u0646",
        }[self]

    def emoji(self) -> str:
        return {
            BadgeKind.FIRST_PURCHASE: "\U0001f389",
            BadgeKind.RENEWED_THRICE: "\U0001f501",
            BadgeKind.HALF_YEAR: "\U0001f31f",
            BadgeKind.FULL_YEAR: "\U0001f3c6",
            BadgeKind.BIG_SPENDER: "\U0001f48e",
            BadgeKind.REFERRER_ROOKIE: "\U0001f91d",
            BadgeKind.REFERRER_PRO: "\U0001f680",
            BadgeKind.EARLY_ADOPTER: "\U0001f947",
        }[self]


__all__ = [
    "BadgeKind",
    "FunnelStage",
    "Granularity",
    "MetricFormat",
    "MetricKey",
    "SegmentKind",
    "TrendDirection",
]
