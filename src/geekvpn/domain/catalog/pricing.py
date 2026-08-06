"""The pricing engine.

One function decides what a customer pays. Everything else in this context
feeds it. Concentrating the arithmetic here, rather than spreading it across the
bot, the Mini App and the admin panel, is the only way three surfaces can be
guaranteed to quote the same number.

The pipeline, in order:

    base price
      -> best applicable campaign        (at most one, never stacked)
      -> coupon                          (stacks only if both sides allow)
      -> global discount ceiling         (policy)
      -> price floor                     (per plan)
      -> round down to the nearest step  (policy)
      = total payable
      -> cashback accrual                (on the amount actually paid)
      -> referral accrual                (on the amount actually paid)

Every step appends a `QuoteLine`. The result is not just a number, it is an
itemised, human-readable breakdown - which is what the Mini App renders, what
the invoice stores, and what a support agent reads back when a customer asks
why they were charged what they were charged.

The engine is a pure function. No I/O, no clock of its own, no repository. That
is what makes the entire pricing surface testable without a database, and what
makes it safe to call on every page view.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from geekvpn.domain.catalog.campaign import Campaign, best_campaign
from geekvpn.domain.catalog.coupon import Coupon
from geekvpn.domain.catalog.errors import CatalogValidationError, PriceFloorBreached
from geekvpn.domain.catalog.money import DEFAULT_ROUNDING_STEP, Money
from geekvpn.domain.catalog.plan import Plan
from geekvpn.domain.catalog.product import Product
from geekvpn.domain.catalog.rewards import (
    CashbackPolicy,
    LoyaltyTier,
    ReferralPolicy,
    RewardAccrual,
    referral_accruals,
)
from geekvpn.domain.catalog.scope import PromotionTarget


class LineKind(enum.StrEnum):
    BASE = "base"
    CAMPAIGN = "campaign"
    COUPON = "coupon"
    ROUNDING = "rounding"
    CASHBACK = "cashback"


@dataclass(frozen=True, slots=True)
class QuoteLine:
    """One row of the price breakdown.

    ``amount`` is always non-negative; ``kind`` says whether it adds or
    subtracts. A signed amount would make it possible to construct a "discount"
    that increases the price.
    """

    kind: LineKind
    label_fa: str
    amount: Money
    reference: str | None = None

    @property
    def is_deduction(self) -> bool:
        return self.kind in (LineKind.CAMPAIGN, LineKind.COUPON, LineKind.ROUNDING)


@dataclass(frozen=True, slots=True)
class PricingPolicy:
    """Platform-wide pricing rules. Every field is admin-configurable.

    These live in the runtime settings store, not in code, because they are the
    knobs an operator turns during a campaign weekend - and a deploy is not an
    acceptable latency for that.
    """

    rounding_step: int = DEFAULT_ROUNDING_STEP
    allow_coupon_campaign_stacking: bool = True
    max_total_discount_bps: int = 7_000
    """70%. A hard ceiling on campaign plus coupon combined. This is the guard
    rail that stops a forgotten 50% campaign plus a 50% coupon from producing
    free subscriptions at scale."""

    cashback: CashbackPolicy = field(default_factory=CashbackPolicy)
    referral: ReferralPolicy = field(default_factory=ReferralPolicy)

    def __post_init__(self) -> None:
        if self.rounding_step <= 0:
            raise CatalogValidationError("Rounding step must be positive.", step=self.rounding_step)
        if not 0 <= self.max_total_discount_bps <= 10_000:
            raise CatalogValidationError(
                "The discount ceiling must be between 0 and 100%.",
                basis_points=self.max_total_discount_bps,
            )


@dataclass(frozen=True, slots=True)
class PricingContext:
    """Everything about the buyer that can move the price or the reward."""

    now: datetime
    user_id: uuid.UUID | None = None
    loyalty_tier: LoyaltyTier = LoyaltyTier.BRONZE
    is_first_purchase: bool = False
    referrer_id: uuid.UUID | None = None
    coupon_redemptions_by_user: int = 0

    def __post_init__(self) -> None:
        if self.now.tzinfo is None:
            raise CatalogValidationError("Pricing context requires an aware datetime.")


@dataclass(frozen=True, slots=True)
class PriceQuote:
    """An itemised, explainable price.

    A quote is a *calculation*, not a reservation. Nothing is held, no stock is
    decremented, and it can be recomputed freely. The order flow re-quotes at
    confirmation time and compares, so a flash sale that ends between "view" and
    "pay" is caught rather than honoured indefinitely.
    """

    plan_id: uuid.UUID
    product_id: uuid.UUID
    base_price: Money
    total: Money
    lines: tuple[QuoteLine, ...]
    cashback: Money
    accruals: tuple[RewardAccrual, ...]
    campaign_id: uuid.UUID | None = None
    campaign_label_fa: str | None = None
    coupon_code: str | None = None
    compare_at_price: Money | None = None
    flash_sale_ends_in: int | None = None

    @property
    def total_discount(self) -> Money:
        return self.base_price - self.total

    @property
    def discount_bps(self) -> int:
        if self.base_price.is_zero:
            return 0
        return (self.total_discount.amount * 10_000) // self.base_price.amount

    @property
    def has_discount(self) -> bool:
        return not self.total_discount.is_zero

    @property
    def effective_price_after_cashback(self) -> Money:
        """Marketing's favourite number: "in effect, you pay X".

        Kept clearly separate from `total`. This is never what is charged.
        """
        return self.total - self.cashback


def quote_plan(
    *,
    plan: Plan,
    product: Product,
    context: PricingContext,
    policy: PricingPolicy | None = None,
    campaigns: list[Campaign] | None = None,
    coupon: Coupon | None = None,
    enforce_purchasable: bool = True,
) -> PriceQuote:
    """Price one plan for one customer at one moment.

    Set ``enforce_purchasable=False`` to price an unpublished plan, which the
    admin preview uses to see exactly what a customer would see before pressing
    publish.
    """
    policy = policy or PricingPolicy()
    campaigns = campaigns or []

    if enforce_purchasable:
        plan.assert_purchasable()

    target = PromotionTarget(plan_id=plan.id, product_id=product.id, tier=product.tier)

    base = plan.base_price
    lines: list[QuoteLine] = [QuoteLine(kind=LineKind.BASE, label_fa=plan.name_fa, amount=base)]

    # -- campaign ----------------------------------------------------------
    chosen = best_campaign(campaigns, target=target, subtotal=base, now=context.now)
    campaign_discount = Money.zero()
    if chosen is not None:
        campaign_discount = chosen.discount_for(base)

    # -- coupon ------------------------------------------------------------
    coupon_discount = Money.zero()
    if coupon is not None:
        coupon.assert_redeemable(
            now=context.now,
            user_id=context.user_id or uuid.UUID(int=0),
            target=target,
            subtotal=base,
            user_redemptions=context.coupon_redemptions_by_user,
            is_first_purchase=context.is_first_purchase,
        )

        stacking_allowed = policy.allow_coupon_campaign_stacking and coupon.stacks_with_campaign

        if chosen is None or stacking_allowed:
            # Coupon applies to what remains after the campaign. Applying both
            # to the original base would make two 50% discounts free.
            coupon_discount = coupon.discount_for(base - campaign_discount)
        else:
            # No stacking: give the customer whichever single discount is
            # larger. Silently ignoring their code because a campaign happens
            # to be running is how a customer concludes the code was fake.
            standalone = coupon.discount_for(base)
            if standalone > campaign_discount:
                campaign_discount = Money.zero()
                chosen = None
                coupon_discount = standalone

    if chosen is not None and campaign_discount:
        lines.append(
            QuoteLine(
                kind=LineKind.CAMPAIGN,
                label_fa=chosen.name_fa,
                amount=campaign_discount,
                reference=chosen.slug,
            )
        )

    if coupon is not None and coupon_discount:
        lines.append(
            QuoteLine(
                kind=LineKind.COUPON,
                label_fa=f"کد تخفیف {coupon.code}",
                amount=coupon_discount,
                reference=coupon.code,
            )
        )

    # -- ceilings and floors -----------------------------------------------
    gross_discount = campaign_discount + coupon_discount
    ceiling = base.percentage(policy.max_total_discount_bps)
    if gross_discount > ceiling:
        gross_discount = ceiling

    total = base - gross_discount

    if total < plan.min_price:
        if coupon is not None:
            # An operator combined a campaign and a coupon that together break
            # this plan's economics. Refuse loudly: silently clamping hides a
            # configuration error that is losing money on every order.
            raise PriceFloorBreached(
                "The combined discount is larger than this plan allows.",
                plan_id=str(plan.id),
                floor=plan.min_price.amount,
                attempted=total.amount,
            )
        total = plan.min_price

    # -- rounding ----------------------------------------------------------
    rounded = total.round_to(policy.rounding_step)
    if rounded < total:
        lines.append(
            QuoteLine(
                kind=LineKind.ROUNDING,
                label_fa="گرد کردن به نفع شما",
                amount=total - rounded,
            )
        )
    total = rounded

    # -- rewards -----------------------------------------------------------
    cashback = policy.cashback.compute(
        paid=total, plan_bps=plan.cashback_bps, tier=context.loyalty_tier
    )
    if cashback:
        lines.append(
            QuoteLine(
                kind=LineKind.CASHBACK,
                label_fa="بازگشت به کیف پول",
                amount=cashback,
            )
        )

    accruals: tuple[RewardAccrual, ...] = ()
    if context.user_id is not None:
        accruals = referral_accruals(
            paid=total,
            buyer_id=context.user_id,
            referrer_id=context.referrer_id,
            policy=policy.referral,
            is_first_purchase=context.is_first_purchase,
        )

    return PriceQuote(
        plan_id=plan.id,
        product_id=product.id,
        base_price=base,
        total=total,
        lines=tuple(lines),
        cashback=cashback,
        accruals=accruals,
        campaign_id=chosen.id if chosen else None,
        campaign_label_fa=chosen.name_fa if chosen else None,
        coupon_code=coupon.code if coupon and coupon_discount else None,
        compare_at_price=plan.compare_at_price,
        flash_sale_ends_in=(chosen.window.seconds_remaining(context.now) if chosen else None),
    )
