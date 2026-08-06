"""Ladder generation.

The arithmetic matters less than the invariants: a longer package must never
look worse than a shorter one on any axis a customer compares.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.application.catalog.duration_ladder import (
    DurationLadderService,
    LadderRequest,
)
from geekvpn.domain.catalog.durations import DEFAULT_LADDER, LADDER, WEEKLY
from geekvpn.domain.catalog.enums import PlanType
from geekvpn.domain.catalog.errors import CatalogError

MONTHLY = 200_000


class RecordingAdmin:
    """Captures the commands instead of touching a repository."""

    def __init__(self) -> None:
        self.commands = []

    async def create_plan(self, command, *, actor_id=None):
        self.commands.append(command)
        return command


@pytest.fixture
def admin() -> RecordingAdmin:
    return RecordingAdmin()


@pytest.fixture
def service(admin: RecordingAdmin) -> DurationLadderService:
    return DurationLadderService(admin)


def traffic_request(**kwargs) -> LadderRequest:
    base = {
        "product_id": uuid.uuid4(),
        "monthly_price": MONTHLY,
        "plan_type": PlanType.TRAFFIC,
        "slug_prefix": "turbo",
        "name_prefix_fa": "\u062a\u0631\u0628\u0648",
        "monthly_quota_gib": 50,
    }
    base.update(kwargs)
    return LadderRequest(**base)


class TestGeneration:
    @pytest.mark.asyncio
    async def test_creates_one_plan_per_rung(self, service, admin) -> None:
        await service.generate(traffic_request())
        assert len(admin.commands) == len(DEFAULT_LADDER)

    @pytest.mark.asyncio
    async def test_slugs_are_unique_and_prefixed(self, service, admin) -> None:
        await service.generate(traffic_request())
        slugs = [c.slug for c in admin.commands]
        assert len(slugs) == len(set(slugs))
        assert all(s.startswith("turbo-") for s in slugs)

    @pytest.mark.asyncio
    async def test_names_are_persian(self, service, admin) -> None:
        await service.generate(traffic_request())
        for command in admin.commands:
            assert not (set(command.name_fa) & set("0123456789"))

    @pytest.mark.asyncio
    async def test_sort_order_follows_term_length(self, service, admin) -> None:
        await service.generate(traffic_request())
        pairs = [(c.sort_order, c.duration_days) for c in admin.commands]
        assert pairs == sorted(pairs)


class TestCustomerFacingInvariants:
    @pytest.mark.asyncio
    async def test_longer_never_cheaper_outright(self, service, admin) -> None:
        await service.generate(traffic_request())
        prices = [c.base_price for c in admin.commands]
        assert prices == sorted(prices)

    @pytest.mark.asyncio
    async def test_longer_is_cheaper_per_month(self, service, admin) -> None:
        await service.generate(traffic_request())
        rates = [c.base_price / (c.duration_days / 30) for c in admin.commands]
        assert rates == sorted(rates, reverse=True)

    @pytest.mark.asyncio
    async def test_volume_scales_with_term(self, service, admin) -> None:
        """Otherwise the longer package is a worse deal per month."""
        await service.generate(traffic_request())
        quotas = [c.quota_gib for c in admin.commands]
        assert quotas == sorted(quotas)

    @pytest.mark.asyncio
    async def test_devices_never_decrease(self, service, admin) -> None:
        await service.generate(traffic_request())
        devices = [c.device_limit for c in admin.commands]
        assert devices == sorted(devices)


class TestCompareAtIsHonest:
    @pytest.mark.asyncio
    async def test_baseline_has_no_struck_price(self, service, admin) -> None:
        await service.generate(traffic_request())
        monthly = next(c for c in admin.commands if c.duration_days == 30)
        assert monthly.compare_at_price is None

    @pytest.mark.asyncio
    async def test_discounted_rungs_show_a_higher_before_price(self, service, admin) -> None:
        await service.generate(traffic_request())
        for command in admin.commands:
            if command.compare_at_price is not None:
                assert command.compare_at_price > command.base_price

    @pytest.mark.asyncio
    async def test_weekly_never_fakes_a_discount(self, service, admin) -> None:
        """The weekly rung is a premium, so there is no honest 'before'."""
        await service.generate(traffic_request(), rungs=LADDER)
        weekly = next(c for c in admin.commands if c.duration_days == WEEKLY.days)
        assert weekly.compare_at_price is None


class TestPlanTypes:
    @pytest.mark.asyncio
    async def test_unlimited_carries_no_quota(self, service, admin) -> None:
        await service.generate(
            traffic_request(plan_type=PlanType.UNLIMITED, monthly_quota_gib=None)
        )
        assert all(c.quota_gib is None for c in admin.commands)

    @pytest.mark.asyncio
    async def test_daily_ceiling_is_constant(self, service, admin) -> None:
        """A fair-use limit that grew with the term would not be a limit."""
        await service.generate(
            traffic_request(
                plan_type=PlanType.DURATION,
                monthly_quota_gib=None,
                daily_quota_gib=5,
            )
        )
        assert {c.daily_quota_gib for c in admin.commands} == {5}


class TestValidation:
    @pytest.mark.asyncio
    async def test_rejects_empty_ladder(self, service) -> None:
        with pytest.raises(CatalogError):
            await service.generate(traffic_request(), rungs=())

    @pytest.mark.asyncio
    async def test_rejects_free_monthly_price(self, service) -> None:
        with pytest.raises(CatalogError):
            await service.generate(traffic_request(monthly_price=0))

    @pytest.mark.asyncio
    async def test_traffic_ladder_needs_a_volume(self, service) -> None:
        with pytest.raises(CatalogError):
            await service.generate(traffic_request(monthly_quota_gib=None))

    @pytest.mark.asyncio
    async def test_duration_ladder_needs_a_daily_limit(self, service) -> None:
        with pytest.raises(CatalogError):
            await service.generate(
                traffic_request(plan_type=PlanType.DURATION, monthly_quota_gib=None)
            )
