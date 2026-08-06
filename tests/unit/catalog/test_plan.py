"""Plan invariants: the three plan types and the price rules.

A plan is the thing a customer buys, so an inconsistent plan is a support
ticket at best and a mispriced sale at worst. The aggregate refuses to exist in
an invalid state rather than trusting callers to be careful.
"""

from __future__ import annotations

import pytest

from geekvpn.domain.catalog.enums import PlanType, PublicationState
from geekvpn.domain.catalog.errors import CatalogError, CatalogValidationError
from geekvpn.domain.catalog.money import Money
from tests.catalog_fakes import make_plan


class TestTrafficPlans:
    def test_requires_a_volume(self) -> None:
        with pytest.raises(CatalogValidationError):
            make_plan(plan_type=PlanType.TRAFFIC, quota_gib=None)

    def test_reports_total_bytes(self) -> None:
        plan = make_plan(plan_type=PlanType.TRAFFIC, quota_gib=60)
        assert plan.total_quota_bytes == 60 * 1024**3

    def test_price_per_gib(self) -> None:
        plan = make_plan(quota_gib=60, base_price=Money(600_000))
        assert plan.price_per_gib == 10_000

    def test_is_not_unlimited(self) -> None:
        assert not make_plan(plan_type=PlanType.TRAFFIC).is_unlimited


class TestUnlimitedPlans:
    def test_must_not_carry_a_volume(self) -> None:
        # An "unlimited" plan with a cap is a lie the storefront would print.
        with pytest.raises(CatalogValidationError):
            make_plan(plan_type=PlanType.UNLIMITED, quota_gib=50)

    def test_valid_unlimited_plan(self) -> None:
        plan = make_plan(plan_type=PlanType.UNLIMITED, quota_gib=None)
        assert plan.is_unlimited
        assert plan.total_quota_bytes is None
        assert plan.price_per_gib is None


class TestDurationPlans:
    def test_requires_a_daily_allowance(self) -> None:
        with pytest.raises(CatalogValidationError):
            make_plan(plan_type=PlanType.DURATION, quota_gib=None, daily_quota_gib=None)

    def test_valid_duration_plan(self) -> None:
        plan = make_plan(plan_type=PlanType.DURATION, quota_gib=None, daily_quota_gib=3)
        assert plan.daily_quota_gib == 3


class TestDurationAndDevices:
    def test_rejects_zero_days(self) -> None:
        with pytest.raises(CatalogValidationError):
            make_plan(duration_days=0)

    def test_rejects_absurd_duration(self) -> None:
        with pytest.raises(CatalogValidationError):
            make_plan(duration_days=100_000)

    def test_rejects_zero_devices(self) -> None:
        with pytest.raises(CatalogValidationError):
            make_plan(device_limit=0)


class TestPriceInvariants:
    def test_compare_at_must_exceed_the_selling_price(self) -> None:
        # Otherwise the storefront strikes through a number *lower* than the
        # price - a fake discount, and in most jurisdictions illegal.
        with pytest.raises(CatalogValidationError):
            make_plan(base_price=Money(680_000), compare_at_price=Money(100_000))

    def test_savings_bps(self) -> None:
        plan = make_plan(base_price=Money(680_000), compare_at_price=Money(850_000))
        assert plan.savings_bps == 2_000  # 20% off the anchor price

    def test_floor_cannot_exceed_the_price(self) -> None:
        with pytest.raises(CatalogValidationError):
            make_plan(base_price=Money(100_000), min_price=Money(200_000))

    def test_rejects_absurd_cashback(self) -> None:
        with pytest.raises(CatalogValidationError):
            make_plan(cashback_bps=9_999)


class TestSlug:
    @pytest.mark.parametrize("bad", ["Geek_Turbo", "geek turbo", "-geek", "", "a" * 65])
    def test_rejects_invalid_slugs(self, bad: str) -> None:
        with pytest.raises(CatalogValidationError):
            make_plan(slug=bad)

    def test_accepts_a_kebab_slug(self) -> None:
        assert make_plan(slug="geek-turbo-60").slug == "geek-turbo-60"


class TestRevalidate:
    def test_catches_damage_done_after_construction(self) -> None:
        """The admin update path assigns attributes directly.

        Without an explicit revalidate() an unlimited plan could be given a
        volume cap and persisted, because __init__ already ran.
        """
        plan = make_plan(plan_type=PlanType.UNLIMITED, quota_gib=None)
        plan.quota_gib = 50
        with pytest.raises(CatalogValidationError):
            plan.revalidate()


class TestPublication:
    def test_draft_plans_are_not_purchasable(self) -> None:
        plan = make_plan(state=PublicationState.DRAFT)
        assert not plan.is_visible
        with pytest.raises(CatalogError):
            plan.assert_purchasable()

    def test_archived_plans_are_not_purchasable(self) -> None:
        plan = make_plan()
        plan.archive()
        with pytest.raises(CatalogError):
            plan.assert_purchasable()

    def test_published_plans_are_purchasable(self) -> None:
        make_plan(state=PublicationState.PUBLISHED).assert_purchasable()


class TestPriceChange:
    def test_records_an_event(self) -> None:
        plan = make_plan(base_price=Money(680_000))
        plan.change_price(Money(590_000))
        assert plan.base_price == Money(590_000)
        events = plan.collect_events()
        assert any(e.name == "catalog.plan.price_changed.v1" for e in events)
