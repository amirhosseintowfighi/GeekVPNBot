"""The duration ladder.

Phase 4 shipped 30-day packages only. Longer terms were requested; this is
the proposal.

Why these rungs, and not a slider:

* **30 / 90 / 180 / 365** map to how people actually budget - monthly, a
  quarter, half a year, a year. A 60-day tier sits too close to 30 to feel
  like a real decision and mostly cannibalises it, so it is deliberately
  absent.
* **7 days** exists as a paid step above the free 100MB trial. It is the
  cheapest way to convert someone who liked the trial but will not commit to
  a month yet.

The discount curve is intentionally *concave*: each step up gives more total
discount but less additional discount per extra month. A linear curve makes
the annual plan too cheap relative to the churn protection it buys, and a
flat curve gives nobody a reason to prepay.

These are catalogue defaults. Every value is overridable per product from the
admin panel - this module only decides what a new product starts life with.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DurationRung:
    days: int
    slug: str
    name_fa: str
    #: Discount off the equivalent number of 30-day terms, in basis points.
    #: Negative means a short-term premium.
    discount_bps: int
    badge_fa: str | None = None
    #: Extra simultaneous devices granted at this term, on top of the
    #: product's base device limit.
    bonus_devices: int = 0

    @property
    def months(self) -> float:
        return self.days / 30

    def price_from_monthly(self, monthly_price: int) -> int:
        """Derive a term price from the product's 30-day price."""
        gross = monthly_price * self.days / 30
        return int(gross * (10_000 - self.discount_bps) / 10_000)

    def savings_from_monthly(self, monthly_price: int) -> int:
        """How much the customer keeps versus paying monthly.

        Negative on the weekly rung, which is correct and is why the
        storefront must not render this number unconditionally.
        """
        straight = int(monthly_price * self.days / 30)
        return straight - self.price_from_monthly(monthly_price)


WEEKLY = DurationRung(
    days=7,
    slug="7d",
    name_fa="\u06cc\u06a9\u200c\u0647\u0641\u062a\u0647\u200c\u0627\u06cc",
    # A premium, not a discount: short terms cost more per day.
    discount_bps=-1_500,
)

MONTHLY = DurationRung(
    days=30,
    slug="30d",
    name_fa="\u06cc\u06a9\u200c\u0645\u0627\u0647\u0647",
    discount_bps=0,
)

QUARTERLY = DurationRung(
    days=90,
    slug="90d",
    name_fa="\u0633\u0647\u200c\u0645\u0627\u0647\u0647",
    discount_bps=1_000,
    badge_fa="\u06f1\u06f0\u066a \u062a\u062e\u0641\u06cc\u0641",
)

SEMIANNUAL = DurationRung(
    days=180,
    slug="180d",
    name_fa="\u0634\u0634\u200c\u0645\u0627\u0647\u0647",
    discount_bps=1_800,
    badge_fa="\u067e\u0631\u0637\u0631\u0641\u062f\u0627\u0631\u062a\u0631\u06cc\u0646",
    bonus_devices=1,
)

ANNUAL = DurationRung(
    days=365,
    slug="365d",
    name_fa="\u06cc\u06a9\u200c\u0633\u0627\u0644\u0647",
    discount_bps=2_500,
    badge_fa="\u0628\u0647\u062a\u0631\u06cc\u0646 \u0627\u0631\u0632\u0634 \u062e\u0631\u06cc\u062f",
    bonus_devices=2,
)

#: Ordered shortest to longest. Storefront rendering relies on this order.
LADDER: tuple[DurationRung, ...] = (WEEKLY, MONTHLY, QUARTERLY, SEMIANNUAL, ANNUAL)

#: What a brand-new product gets by default. The weekly rung is opt-in per
#: product, because it only makes sense on cheap tiers - a one-week Elite
#: package is priced high enough that nobody buys it.
DEFAULT_LADDER: tuple[DurationRung, ...] = (MONTHLY, QUARTERLY, SEMIANNUAL, ANNUAL)

BY_SLUG = {rung.slug: rung for rung in LADDER}
BY_DAYS = {rung.days: rung for rung in LADDER}


def rung_for_days(days: int) -> DurationRung | None:
    return BY_DAYS.get(days)


def effective_monthly_price(monthly_price: int, rung: DurationRung) -> int:
    """What the customer effectively pays per 30 days on this rung.

    Used for the "only X per month" line, which is the single most effective
    argument for a longer term.
    """
    total = rung.price_from_monthly(monthly_price)
    return int(total / rung.months) if rung.months else total
