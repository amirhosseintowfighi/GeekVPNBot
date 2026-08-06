"""Coupons, campaigns, flash sales and promotion scope.

The rules here decide who gets money off. Every branch is a way to give away
revenue by accident, so each one is pinned.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from geekvpn.domain.catalog.campaign import best_campaign
from geekvpn.domain.catalog.coupon import normalise_code
from geekvpn.domain.catalog.discount import Discount
from geekvpn.domain.catalog.enums import (
    CampaignKind,
    CouponKind,
    ProductTier,
    PublicationState,
)
from geekvpn.domain.catalog.errors import (
    CatalogError,
    CatalogValidationError,
    CouponExhausted,
    CouponExpired,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.scope import PromotionScope, PromotionTarget
from geekvpn.domain.catalog.window import TimeWindow
from tests.catalog_fakes import NOW, make_campaign, make_coupon, running_window

PLAN_ID = uuid.uuid4()
PRODUCT_ID = uuid.uuid4()
TARGET = PromotionTarget(plan_id=PLAN_ID, product_id=PRODUCT_ID, tier=ProductTier.ELITE)
SUBTOTAL = Money(680_000)


class TestDiscount:
    def test_percentage(self) -> None:
        assert Discount.percentage(1_500).compute(SUBTOTAL) == Money(102_000)

    def test_percentage_cap(self) -> None:
        capped = Discount.percentage(2_000, cap=Money(50_000))
        assert capped.compute(SUBTOTAL) == Money(50_000)

    def test_fixed(self) -> None:
        assert Discount.fixed(50_000).compute(SUBTOTAL) == Money(50_000)

    def test_fixed_never_exceeds_the_subtotal(self) -> None:
        # Otherwise a 900,000 coupon on a 150,000 package owes the customer
        # money.
        assert Discount.fixed(900_000).compute(Money(150_000)) == Money(150_000)

    def test_rejects_more_than_one_hundred_percent(self) -> None:
        with pytest.raises(CatalogValidationError):
            Discount.percentage(12_000)

    def test_value_is_always_a_plain_int(self) -> None:
        """Regression: the mapper once wrapped fixed amounts in Money().

        `value` is basis points for a percentage and Toman for a fixed amount,
        but it is an `int` in both cases - `kind` is the discriminator, not the
        Python type.
        """
        assert isinstance(Discount.percentage(1_000).value, int)
        assert isinstance(Discount.fixed(50_000).value, int)


class TestTimeWindow:
    def test_rejects_naive_datetimes(self) -> None:
        # A naive datetime in a promotion window is a flash sale that ends at
        # the wrong hour for everyone outside the server's timezone.
        from datetime import datetime

        with pytest.raises(CatalogValidationError):
            TimeWindow(ends_at=datetime(2026, 9, 1))

    def test_rejects_backwards_windows(self) -> None:
        with pytest.raises(CatalogValidationError):
            TimeWindow(starts_at=NOW, ends_at=NOW - timedelta(hours=1))

    def test_contains(self) -> None:
        assert running_window().contains(NOW)

    def test_countdown(self) -> None:
        assert running_window().seconds_remaining(NOW) == 5 * 3600

    def test_unbounded_window_has_no_countdown(self) -> None:
        assert TimeWindow().is_unbounded
        assert TimeWindow().seconds_remaining(NOW) is None


class TestPromotionScope:
    def test_empty_scope_is_global(self) -> None:
        assert PromotionScope().is_global
        assert PromotionScope().matches_target(TARGET)

    def test_matches_by_tier(self) -> None:
        scope = PromotionScope(tiers=frozenset({ProductTier.ELITE}))
        assert scope.matches_target(TARGET)

    def test_matches_by_plan(self) -> None:
        assert PromotionScope(plan_ids=frozenset({PLAN_ID})).matches_target(TARGET)

    def test_rejects_a_different_tier(self) -> None:
        scope = PromotionScope(tiers=frozenset({ProductTier.DIRECT}))
        assert not scope.matches_target(TARGET)

    def test_dimensions_are_a_union_not_an_intersection(self) -> None:
        """Matching any one dimension is enough.

        "Elite tier, or specifically this plan" is the useful semantic. An
        intersection would mean a scope naming a plan *and* a tier silently
        matched almost nothing.
        """
        scope = PromotionScope(
            plan_ids=frozenset({uuid.uuid4()}),
            tiers=frozenset({ProductTier.ELITE}),
        )
        assert scope.matches_target(TARGET)


class TestFlashSales:
    def test_flash_sale_must_have_an_end_time(self) -> None:
        # A flash sale without an end is just a price cut, and the countdown
        # the Mini App renders would have nothing to count down to.
        with pytest.raises(CatalogValidationError):
            make_campaign(kind=CampaignKind.FLASH_SALE, window=TimeWindow())

    def test_exposes_a_countdown(self) -> None:
        sale = make_campaign(kind=CampaignKind.FLASH_SALE, window=running_window())
        assert sale.seconds_remaining(NOW) == 5 * 3600

    def test_stock_limits(self) -> None:
        sale = make_campaign(max_redemptions=10, redemption_count=9)
        assert sale.remaining_stock == 1
        assert not sale.is_sold_out
        sale.consume(now=NOW)
        assert sale.is_sold_out
        assert not sale.is_running(NOW)

    def test_cannot_oversell(self) -> None:
        sale = make_campaign(max_redemptions=1, redemption_count=1)
        with pytest.raises(CatalogError):
            sale.consume(now=NOW)


class TestBestCampaign:
    """Campaigns never stack with each other - exactly one can apply."""

    def test_picks_the_largest_discount(self) -> None:
        small = make_campaign(slug="small", discount=Discount.percentage(500))
        big = make_campaign(slug="big", discount=Discount.percentage(2_000))
        assert best_campaign([small, big], target=TARGET, subtotal=SUBTOTAL, now=NOW) is big

    def test_priority_beats_a_larger_discount(self) -> None:
        # Priority is the operator's override: a launch campaign can be pinned
        # above a bigger seasonal one.
        pinned = make_campaign(slug="pinned", discount=Discount.percentage(500), priority=10)
        big = make_campaign(slug="big", discount=Discount.percentage(2_000))
        assert best_campaign([pinned, big], target=TARGET, subtotal=SUBTOTAL, now=NOW) is pinned

    def test_skips_sold_out(self) -> None:
        sold_out = make_campaign(
            slug="sold-out",
            discount=Discount.percentage(9_000),
            max_redemptions=10,
            redemption_count=10,
        )
        small = make_campaign(slug="small", discount=Discount.percentage(500))
        assert best_campaign([sold_out, small], target=TARGET, subtotal=SUBTOTAL, now=NOW) is small

    def test_skips_expired(self) -> None:
        expired = make_campaign(
            slug="expired",
            discount=Discount.percentage(9_000),
            window=TimeWindow(ends_at=NOW - timedelta(minutes=1)),
        )
        small = make_campaign(slug="small", discount=Discount.percentage(500))
        assert best_campaign([expired, small], target=TARGET, subtotal=SUBTOTAL, now=NOW) is small

    def test_skips_paused(self) -> None:
        paused = make_campaign(
            slug="paused",
            discount=Discount.percentage(9_000),
            state=PublicationState.DRAFT,
        )
        small = make_campaign(slug="small", discount=Discount.percentage(500))
        assert best_campaign([paused, small], target=TARGET, subtotal=SUBTOTAL, now=NOW) is small

    def test_skips_out_of_scope(self) -> None:
        elsewhere = make_campaign(
            slug="elsewhere",
            discount=Discount.percentage(9_000),
            scope=PromotionScope(tiers=frozenset({ProductTier.DIRECT})),
        )
        assert best_campaign([elsewhere], target=TARGET, subtotal=SUBTOTAL, now=NOW) is None

    def test_tie_break_is_deterministic(self) -> None:
        """Equal priority and equal discount must resolve the same way always.

        Otherwise two customers loading the same page see different campaign
        names on the same price.
        """
        a = make_campaign(
            campaign_id=uuid.UUID(int=1), slug="a", discount=Discount.percentage(1_000)
        )
        b = make_campaign(
            campaign_id=uuid.UUID(int=2), slug="b", discount=Discount.percentage(1_000)
        )
        first = best_campaign([a, b], target=TARGET, subtotal=SUBTOTAL, now=NOW)
        second = best_campaign([b, a], target=TARGET, subtotal=SUBTOTAL, now=NOW)
        assert first is second

    def test_no_campaigns(self) -> None:
        assert best_campaign([], target=TARGET, subtotal=SUBTOTAL, now=NOW) is None


class TestCouponCodes:
    def test_trims_and_uppercases(self) -> None:
        assert normalise_code("  welcome10 ") == "WELCOME10"

    def test_folds_persian_digits(self) -> None:
        # An Iranian customer typing on a Persian keyboard produces ۱۰, not 10.
        # Rejecting that would be a support ticket for every numeric code.
        assert normalise_code("WELCOME۱۰") == "WELCOME10"

    def test_folds_arabic_indic_digits(self) -> None:
        assert normalise_code("WELCOME١٠") == "WELCOME10"

    @pytest.mark.parametrize("bad", ["a", "", "-BAD", "A" * 40])
    def test_rejects_malformed_codes(self, bad: str) -> None:
        with pytest.raises(CatalogValidationError):
            normalise_code(bad)


class TestCouponRedemption:
    def test_a_valid_coupon_passes(self) -> None:
        make_coupon().assert_redeemable(
            now=NOW, user_id=uuid.uuid4(), target=TARGET, subtotal=SUBTOTAL
        )

    def test_expired(self) -> None:
        coupon = make_coupon(window=TimeWindow(ends_at=NOW - timedelta(days=1)))
        with pytest.raises(CouponExpired):
            coupon.assert_redeemable(
                now=NOW, user_id=uuid.uuid4(), target=TARGET, subtotal=SUBTOTAL
            )

    def test_globally_exhausted(self) -> None:
        coupon = make_coupon(max_redemptions=5, redemption_count=5)
        with pytest.raises(CouponExhausted):
            coupon.assert_redeemable(
                now=NOW, user_id=uuid.uuid4(), target=TARGET, subtotal=SUBTOTAL
            )

    def test_per_user_limit(self) -> None:
        with pytest.raises(CouponExhausted):
            make_coupon().assert_redeemable(
                now=NOW,
                user_id=uuid.uuid4(),
                target=TARGET,
                subtotal=SUBTOTAL,
                user_redemptions=1,
            )

    def test_first_purchase_only(self) -> None:
        with pytest.raises(CatalogError):
            make_coupon(first_purchase_only=True).assert_redeemable(
                now=NOW,
                user_id=uuid.uuid4(),
                target=TARGET,
                subtotal=SUBTOTAL,
                is_first_purchase=False,
            )

    def test_minimum_order_amount(self) -> None:
        with pytest.raises(CatalogError):
            make_coupon(min_order_amount=Money(1_000_000)).assert_redeemable(
                now=NOW, user_id=uuid.uuid4(), target=TARGET, subtotal=SUBTOTAL
            )

    def test_targeted_coupon_rejects_other_users(self) -> None:
        coupon = make_coupon(kind=CouponKind.TARGETED, target_user_id=uuid.uuid4())
        with pytest.raises(CatalogError):
            coupon.assert_redeemable(
                now=NOW, user_id=uuid.uuid4(), target=TARGET, subtotal=SUBTOTAL
            )

    def test_targeted_coupon_accepts_its_owner(self) -> None:
        owner = uuid.uuid4()
        coupon = make_coupon(kind=CouponKind.TARGETED, target_user_id=owner)
        coupon.assert_redeemable(now=NOW, user_id=owner, target=TARGET, subtotal=SUBTOTAL)

    def test_targeted_coupon_requires_an_owner(self) -> None:
        with pytest.raises(CatalogValidationError):
            make_coupon(kind=CouponKind.TARGETED)

    def test_single_use_coupon_cannot_allow_many_uses(self) -> None:
        with pytest.raises(CatalogValidationError):
            make_coupon(kind=CouponKind.SINGLE_USE, max_redemptions=99)

    def test_redeem_records_an_event(self) -> None:
        coupon = make_coupon()
        coupon.redeem(user_id=uuid.uuid4(), discount=Money(68_000))
        assert coupon.redemption_count == 1
        assert any(e.name == "catalog.coupon.redeemed.v1" for e in coupon.collect_events())
