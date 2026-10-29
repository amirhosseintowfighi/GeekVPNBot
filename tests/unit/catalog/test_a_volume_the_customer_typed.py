"""A volume the customer typed: its quote, and the order checkout places for it."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from geekvpn.application.catalog.policy_provider import PricingPolicyProvider
from geekvpn.application.catalog.quoting_service import QuotingService
from geekvpn.domain.catalog.enums import PlanType
from geekvpn.domain.catalog.errors import CatalogValidationError
from geekvpn.domain.catalog.money import Money
from geekvpn.infrastructure.bot.checkout import BotCheckoutAdapter
from tests.catalog_fakes import (
    FakeCampaignRepository,
    FakeClock,
    FakeCouponRepository,
    FakePlanRepository,
    FakeProductRepository,
    FakeSettingsStore,
    make_plan,
    make_product,
)

CATEGORY = uuid.uuid4()


async def _shop(
    retail: dict[uuid.UUID, Money] | None = None,
) -> tuple[QuotingService, dict[str, uuid.UUID]]:
    products = FakeProductRepository()
    plans = FakePlanRepository()
    ids: dict[str, uuid.UUID] = {}
    ladder = ((10, 100_000, 270_000), (20, 180_000, 480_000), (50, 400_000, 1_080_000))
    for gib, monthly, quarterly in ladder:
        product = make_product(category_id=CATEGORY, slug=f"v{gib}", name_fa=f"{gib}GB")
        await products.add(product)
        for days, price in ((30, monthly), (90, quarterly)):
            plan = make_plan(
                product_id=product.id,
                slug=f"v{gib}-{days}",
                duration_days=days,
                quota_gib=gib * days // 30,
                base_price=Money(price),
            )
            await plans.add(plan)
            ids[f"{gib}/{days}"] = plan.id
    # Another kind of service, with its own prices, which must not leak in.
    other = make_product(slug="elite", name_fa="Elite")
    await products.add(other)
    await plans.add(
        make_plan(product_id=other.id, slug="elite-15", quota_gib=15, base_price=Money(50_000))
    )
    service = QuotingService(
        plans=plans,
        products=products,
        campaigns=FakeCampaignRepository(),
        coupons=FakeCouponRepository(),
        policies=PricingPolicyProvider(FakeSettingsStore()),
        clock=FakeClock(),
        default_retail=retail,
    )
    return service, ids


async def test_a_typed_volume_is_priced_between_the_packages_of_its_term() -> None:
    service, ids = await _shop()
    quote = await service.quote(plan_id=ids["10/30"], custom_gib=35)
    assert quote.total == Money(290_000)


async def test_a_longer_term_prices_from_that_terms_packages() -> None:
    service, ids = await _shop()
    # 35GB a month for three months is 105GB, between 60GB and 150GB.
    quote = await service.quote(plan_id=ids["10/90"], custom_gib=35)
    assert quote.total == Money(780_000)


async def test_less_than_the_smallest_package_is_refused_in_monthly_terms() -> None:
    service, ids = await _shop()
    with pytest.raises(CatalogValidationError) as refused:
        await service.quote(plan_id=ids["20/90"], custom_gib=9)
    assert refused.value.details["minimum"] == 10


async def test_the_custom_package_carries_the_volume_the_customer_asked_for() -> None:
    service, ids = await _shop()
    package, _ = await service.custom_package(plan_id=ids["20/90"], monthly_gib=35)
    assert package.quota_gib == 105
    assert package.duration_days == 90
    assert package.plan_type is PlanType.TRAFFIC
    assert "دلخواه" in package.name_fa


async def test_a_resellers_customer_is_quoted_on_the_resellers_prices() -> None:
    service, ids = await _shop()
    retail = {ids["20/30"]: Money(200_000), ids["50/30"]: Money(500_000)}
    quote = await service.quote(plan_id=ids["20/30"], custom_gib=35, retail_prices=retail)
    assert quote.total == Money(350_000)


# -- checkout ----------------------------------------------------------------


class _Reached(Exception):
    """Raised where the payment scope would start: the order is placed by then."""


class _Bridge:
    async def telegram_id(self, user_id: uuid.UUID) -> int:
        return 555

    async def run(self, work: object) -> object:
        raise _Reached


class _Orders:
    def __init__(self) -> None:
        self.placed: dict[str, object] = {}

    async def place(self, **kwargs: object) -> SimpleNamespace:
        self.placed = kwargs
        return SimpleNamespace(id="order-1", number="1")


class _OrderHistory:
    async def has_completed_order(self, telegram_id: int) -> bool:
        return True


class _Session:
    async def commit(self) -> None:
        return None


class _Subscriptions:
    async def get(self, subscription_id: str) -> SimpleNamespace:
        return SimpleNamespace(id=subscription_id, user_id=555)


async def _checkout(service: QuotingService) -> tuple[BotCheckoutAdapter, _Orders]:
    orders = _Orders()
    adapter = BotCheckoutAdapter(  # type: ignore[arg-type]
        bridge=_Bridge(),
        quoting=service,
        orders=orders,
        order_repository=_OrderHistory(),
        provisioning=object(),
        session=_Session(),
        plans=object(),
        coupons=object(),
        subscriptions=_Subscriptions(),
        clock=FakeClock(),
        jalali_year=1405,
    )
    return adapter, orders


async def test_the_order_for_a_typed_volume_carries_that_volume_and_price() -> None:
    service, ids = await _shop()
    adapter, orders = await _checkout(service)
    with pytest.raises(_Reached):
        await adapter.begin_card(uuid.uuid4(), plan_id=ids["10/90"], custom_gib=35)
    assert orders.placed["traffic_mib"] == 105 * 1024
    assert orders.placed["duration_days"] == 90
    assert orders.placed["total"] == Money(780_000)
    assert "دلخواه" in str(orders.placed["plan_name_fa"])


async def test_a_typed_volume_can_renew_a_service() -> None:
    service, ids = await _shop()
    adapter, orders = await _checkout(service)
    with pytest.raises(_Reached):
        await adapter.begin_card(
            uuid.uuid4(), plan_id=ids["20/30"], custom_gib=35, renews_subscription_id="sub-1"
        )
    assert orders.placed["is_renewal"] is True
    assert orders.placed["renews_subscription_id"] == "sub-1"
    assert orders.placed["traffic_mib"] == 35 * 1024
