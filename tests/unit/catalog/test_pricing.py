"""The pricing pipeline.

Order is the design, and it is load-bearing:

    base
      -> best campaign
      -> coupon
      -> combined discount ceiling
      -> plan price floor
      -> round down
      -> cashback (disclosed, not deducted)
      -> referral accruals (disclosed, not deducted)

Every test below pins one step or one interaction between steps.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.domain.catalog.discount import Discount
from geekvpn.domain.catalog.enums import CampaignKind, PublicationState
from geekvpn.domain.catalog.errors import (
    CatalogError,
    CatalogValidationError,
    PriceFloorBreached,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.pricing import (
    LineKind,
    PricingContext,
    PricingPolicy,
    quote_plan,
)
from geekvpn.domain.catalog.rewards import LoyaltyTier, ReferralPolicy
from tests.catalog_fakes import (
    NOW,
    make_campaign,
    make_coupon,
    make_plan,
    make_product,
    running_window,
)


def _context(**kw: object) -> PricingContext:
    kw.setdefault("now", NOW)
    kw.setdefault("user_id", uuid.uuid4())
    return PricingContext(**kw)  # type: ignore[arg-type]


def _pair(**plan_kw: object):
    product = make_product()
    plan_kw.setdefault("product_id", product.id)
    return make_plan(**plan_kw), product


class TestContext:
    def test_rejects_naive_datetimes(self) -> None:
        from datetime import datetime

        with pytest.raises(CatalogValidationError):
            PricingContext(now=datetime(2026, 8, 2, 12, 0))


class TestBaseline:
    def test_no_promotions_means_the_base_price(self) -> None:
        plan, product = _pair()
        quote = quote_plan(plan=plan, product=product, context=_context(), policy=PricingPolicy())
        assert quote.total == Money(680_000)
        assert not quote.has_discount
        assert quote.total_discount.is_zero

    def test_carries_the_compare_at_anchor(self) -> None:
        plan, product = _pair(compare_at_price=Money(850_000))
        quote = quote_plan(plan=plan, product=product, context=_context(), policy=PricingPolicy())
        assert quote.compare_at_price == Money(850_000)


class TestCampaigns:
    def test_applies_the_best_campaign(self) -> None:
        plan, product = _pair()
        campaign = make_campaign(discount=Discount.percentage(1_500))
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(),
            policy=PricingPolicy(),
            campaigns=[campaign],
        )
        assert quote.total == Money(578_000)
        assert quote.campaign_id == campaign.id
        assert quote.campaign_label_fa

    def test_exposes_a_flash_sale_countdown(self) -> None:
        plan, product = _pair()
        sale = make_campaign(kind=CampaignKind.FLASH_SALE, window=running_window())
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(),
            policy=PricingPolicy(),
            campaigns=[sale],
        )
        assert quote.flash_sale_ends_in == 5 * 3600


class TestStacking:
    def test_coupon_applies_to_the_post_campaign_subtotal(self) -> None:
        """Sequential, not additive.

        15% then 10% is 23.5% off, not 25%. Additive stacking is how a
        promotion stack accidentally reaches 100%.
        """
        plan, product = _pair()
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(),
            policy=PricingPolicy(allow_coupon_campaign_stacking=True),
            campaigns=[make_campaign(discount=Discount.percentage(1_500))],
            coupon=make_coupon(code="EXTRA10", discount=Discount.percentage(1_000)),
        )
        assert quote.total == Money(520_000)
        assert quote.coupon_code == "EXTRA10"

    def test_when_stacking_is_off_the_better_one_wins(self) -> None:
        plan, product = _pair()
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(),
            policy=PricingPolicy(allow_coupon_campaign_stacking=False),
            campaigns=[make_campaign(discount=Discount.percentage(1_500))],
            coupon=make_coupon(code="HALFOFF", discount=Discount.percentage(3_000)),
        )
        assert quote.total == Money(476_000)

    def test_the_losing_campaign_is_dropped_entirely(self) -> None:
        # Showing a campaign line for a discount that was not applied is worse
        # than showing nothing: the breakdown would not add up.
        plan, product = _pair()
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(),
            policy=PricingPolicy(allow_coupon_campaign_stacking=False),
            campaigns=[make_campaign(discount=Discount.percentage(1_500))],
            coupon=make_coupon(code="HALFOFF", discount=Discount.percentage(3_000)),
        )
        assert quote.campaign_id is None
        assert not any(line.kind is LineKind.CAMPAIGN for line in quote.lines)

    def test_the_losing_coupon_is_dropped_entirely(self) -> None:
        plan, product = _pair()
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(),
            policy=PricingPolicy(allow_coupon_campaign_stacking=False),
            campaigns=[make_campaign(discount=Discount.percentage(1_500))],
            coupon=make_coupon(code="TINY", discount=Discount.percentage(200)),
        )
        assert quote.total == Money(578_000)
        assert quote.coupon_code is None


class TestCeilingAndFloor:
    def test_combined_discount_ceiling(self) -> None:
        plan, product = _pair()
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(),
            policy=PricingPolicy(max_total_discount_bps=7_000),
            campaigns=[make_campaign(discount=Discount.percentage(6_000))],
            coupon=make_coupon(code="HUGE", discount=Discount.percentage(6_000)),
        )
        assert quote.discount_bps <= 7_000
        assert quote.total == Money(204_000)

    def test_a_campaign_breach_clamps_silently(self) -> None:
        """Nobody asked for this discount, so quietly honouring the floor is
        the right behaviour - the customer still gets a good price."""
        plan, product = _pair(min_price=Money(600_000))
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(),
            policy=PricingPolicy(),
            campaigns=[make_campaign(discount=Discount.percentage(1_500))],
        )
        assert quote.total == Money(600_000)

    def test_a_coupon_breach_raises(self) -> None:
        """The customer explicitly typed a code, so they must be told it
        cannot be honoured rather than silently shortchanged."""
        plan, product = _pair(min_price=Money(600_000))
        with pytest.raises(PriceFloorBreached):
            quote_plan(
                plan=plan,
                product=product,
                context=_context(),
                policy=PricingPolicy(),
                coupon=make_coupon(code="DEEP", discount=Discount.percentage(5_000)),
            )


class TestRounding:
    def test_rounds_down_to_the_step(self) -> None:
        plan, product = _pair(base_price=Money(187_777), quota_gib=10)
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(),
            policy=PricingPolicy(rounding_step=1_000),
        )
        assert quote.total == Money(187_000)

    def test_rounding_is_always_in_the_customers_favour(self) -> None:
        plan, product = _pair(base_price=Money(187_777), quota_gib=10)
        quote = quote_plan(plan=plan, product=product, context=_context(), policy=PricingPolicy())
        assert quote.total <= plan.base_price
        assert quote.total.amount % 1_000 == 0


class TestCashbackAndAccruals:
    def test_cashback_does_not_reduce_the_invoice(self) -> None:
        plan, product = _pair(cashback_bps=500)
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(loyalty_tier=LoyaltyTier.GOLD),
            policy=PricingPolicy(),
        )
        assert quote.total == Money(680_000)
        assert quote.cashback == Money(51_000)

    def test_cashback_lines_are_not_deductions(self) -> None:
        plan, product = _pair(cashback_bps=500)
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(loyalty_tier=LoyaltyTier.GOLD),
            policy=PricingPolicy(),
        )
        cashback_lines = [line for line in quote.lines if line.kind is LineKind.CASHBACK]
        assert cashback_lines
        assert all(not line.is_deduction for line in cashback_lines)

    def test_effective_price_after_cashback(self) -> None:
        plan, product = _pair(cashback_bps=500)
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(loyalty_tier=LoyaltyTier.BRONZE),
            policy=PricingPolicy(),
        )
        assert quote.effective_price_after_cashback == quote.total - quote.cashback

    def test_referral_accruals_are_attached(self) -> None:
        plan, product = _pair()
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(is_first_purchase=True, referrer_id=uuid.uuid4()),
            policy=PricingPolicy(referral=ReferralPolicy(first_purchase_bps=1_000)),
        )
        assert quote.accruals


class TestPurchasability:
    def test_draft_plans_cannot_be_quoted(self) -> None:
        plan, product = _pair(state=PublicationState.DRAFT)
        with pytest.raises(CatalogError):
            quote_plan(plan=plan, product=product, context=_context(), policy=PricingPolicy())

    def test_admin_preview_bypasses_the_check(self) -> None:
        # The admin needs to see what a package *would* cost before publishing.
        plan, product = _pair(state=PublicationState.DRAFT)
        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(),
            policy=PricingPolicy(),
            enforce_purchasable=False,
        )
        assert quote.total == Money(680_000)


class TestReconciliation:
    """The breakdown the customer sees must add up. Always."""

    @pytest.mark.parametrize("scenario", ["plain", "campaign", "coupon", "campaign+coupon"])
    def test_lines_reconcile_to_the_total(self, scenario: str) -> None:
        plan, product = _pair(cashback_bps=500, compare_at_price=Money(850_000))
        kwargs: dict[str, object] = {}
        if "campaign" in scenario:
            kwargs["campaigns"] = [make_campaign(discount=Discount.percentage(1_500))]
        if "coupon" in scenario:
            kwargs["coupon"] = make_coupon(discount=Discount.percentage(1_000))

        quote = quote_plan(
            plan=plan,
            product=product,
            context=_context(loyalty_tier=LoyaltyTier.GOLD),
            policy=PricingPolicy(),
            **kwargs,  # type: ignore[arg-type]
        )

        base = next(line for line in quote.lines if line.kind is LineKind.BASE)
        deductions = sum(line.amount.amount for line in quote.lines if line.is_deduction)
        assert base.amount.amount - deductions == quote.total.amount
        assert quote.total >= plan.min_price
        assert quote.total <= plan.base_price
