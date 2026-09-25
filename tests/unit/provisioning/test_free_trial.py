"""The Android app's free trial: once per customer, a real order per tier."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.provisioning.free_trial import (
    TRIAL_DURATION_DAYS,
    TRIAL_TRAFFIC_MIB,
    FreeTrial,
)
from geekvpn.application.provisioning.order_service import OrderService
from geekvpn.application.provisioning.provisioning_service import ProvisioningService
from geekvpn.domain.catalog.enums import PlanType, ProductTier, PublicationState
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.plan import Plan
from geekvpn.domain.catalog.product import Product
from geekvpn.domain.provisioning.enums import OrderSource, OrderState
from geekvpn.domain.provisioning.errors import FreeTrialAlreadyClaimed, FreeTrialUnavailable
from tests.unit.provisioning.fakes import (
    UNREACHABLE,
    FakePanel,
    FakePanelProvider,
    FrozenClock,
    InMemoryNodes,
    InMemoryOrders,
    InMemorySubscriptions,
    RecordingPublisher,
    SequentialIds,
    SequentialNumbers,
    node,
)

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
USER = 777


class InMemoryClaims:
    def __init__(self) -> None:
        self.rows: dict[int, datetime] = {}

    async def has_claimed(self, user_id: int) -> bool:
        return user_id in self.rows

    async def claim(self, user_id: int, *, at: datetime) -> bool:
        if user_id in self.rows:
            return False
        self.rows[user_id] = at
        return True


class Catalogue:
    """Both catalog ports over one list of products and plans."""

    def __init__(self, products: Sequence[Product], plans: Sequence[Plan]) -> None:
        self._products = list(products)
        self._plans = list(plans)

    async def list_all(
        self, *, category_id: uuid.UUID | None = None, published_only: bool = False
    ) -> Sequence[Product]:
        return [p for p in self._products if not published_only or p.is_visible]

    async def list_for_product(
        self, product_id: uuid.UUID, *, published_only: bool = False
    ) -> Sequence[Plan]:
        return [
            p
            for p in self._plans
            if p.product_id == product_id and (not published_only or p.is_visible)
        ]


def product(tier: ProductTier, *, published: bool = True, featured: bool = False) -> Product:
    return Product(
        product_id=uuid.uuid4(),
        category_id=uuid.uuid4(),
        slug=f"geek-{tier.value}-{uuid.uuid4().hex[:6]}",
        tier=tier,
        name_fa=f"گیک {tier.value}",
        state=PublicationState.PUBLISHED if published else PublicationState.DRAFT,
        is_featured=featured,
    )


def plan(owner: Product, *, days: int, price: int, published: bool = True) -> Plan:
    return Plan(
        plan_id=uuid.uuid4(),
        product_id=owner.id,
        slug=f"plan-{uuid.uuid4().hex[:8]}",
        plan_type=PlanType.TRAFFIC,
        name_fa=f"{days} روزه",
        duration_days=days,
        base_price=Money(price),
        quota_gib=20,
        state=PublicationState.PUBLISHED if published else PublicationState.DRAFT,
    )


def build(
    catalogue: Catalogue, *, panel: FakePanel | None = None
) -> tuple[FreeTrial, InMemoryClaims, InMemoryOrders, FakePanel]:
    orders = InMemoryOrders()
    claims = InMemoryClaims()
    panel = panel or FakePanel()
    clock = FrozenClock(NOW)
    events = RecordingPublisher()
    trial = FreeTrial(
        claims=claims,
        products=catalogue,  # type: ignore[arg-type]
        plans=catalogue,  # type: ignore[arg-type]
        orders=OrderService(
            orders=orders,
            clock=clock,
            ids=SequentialIds("ord"),
            numbers=SequentialNumbers(),
            events=events,
        ),
        order_repository=orders,
        provisioning=ProvisioningService(
            orders=orders,
            subscriptions=InMemorySubscriptions(),
            nodes=InMemoryNodes(node("node-de")),
            panels=FakePanelProvider(panel),
            clock=clock,
            ids=SequentialIds("sub"),
            events=events,
        ),
        clock=clock,
        jalali_year=1405,
    )
    return trial, claims, orders, panel


def shop() -> tuple[Catalogue, Product, Product]:
    tunnel = product(ProductTier.TUNNEL)
    direct = product(ProductTier.DIRECT)
    elite = product(ProductTier.ELITE)
    return (
        Catalogue(
            [tunnel, direct, elite],
            [
                plan(tunnel, days=30, price=200_000),
                plan(tunnel, days=7, price=60_000),
                plan(direct, days=30, price=90_000),
                plan(elite, days=7, price=150_000),
            ],
        ),
        tunnel,
        direct,
    )


@pytest.mark.asyncio
async def test_a_tunnel_and_a_direct_service_are_delivered() -> None:
    catalogue, tunnel, direct = shop()
    trial, _, orders, panel = build(catalogue)

    placed = await trial.place(USER)
    delivery = await trial.deliver(placed)

    assert len(delivery.subscriptions) == 2
    assert delivery.pending == 0
    assert {order.product_id for order in placed} == {str(tunnel.id), str(direct.id)}
    assert all(orders.rows[o.id].state is OrderState.ACTIVE for o in placed)
    assert len(panel.created) == 2


@pytest.mark.asyncio
async def test_the_trial_is_small_short_free_and_marked_as_a_trial() -> None:
    catalogue, _, _ = shop()
    trial, _, _, panel = build(catalogue)

    placed = await trial.place(USER)
    await trial.deliver(placed)

    for order in placed:
        assert order.total == Money(0)
        assert order.source is OrderSource.TRIAL
        assert order.traffic_mib == TRIAL_TRAFFIC_MIB
        assert order.duration_days == TRIAL_DURATION_DAYS
    for spec in panel.created:
        assert spec.quota.total_bytes == TRIAL_TRAFFIC_MIB * 1024 * 1024
        assert spec.expires_at == NOW + timedelta(days=TRIAL_DURATION_DAYS)


@pytest.mark.asyncio
async def test_the_shortest_plan_of_the_tier_is_the_one_borrowed() -> None:
    catalogue, tunnel, _ = shop()
    trial, _, _, _ = build(catalogue)

    placed = await trial.place(USER)

    tunnel_order = next(o for o in placed if o.product_id == str(tunnel.id))
    seven_days = next(
        p for p in await catalogue.list_for_product(tunnel.id) if p.duration_days == 7
    )
    assert tunnel_order.plan_id == str(seven_days.id)


@pytest.mark.asyncio
async def test_a_second_claim_is_refused() -> None:
    catalogue, _, _ = shop()
    trial, _, orders, _ = build(catalogue)
    await trial.deliver(await trial.place(USER))

    with pytest.raises(FreeTrialAlreadyClaimed):
        await trial.place(USER)
    assert len(orders.rows) == 2
    assert not (await trial.offer(USER)).available


@pytest.mark.asyncio
async def test_the_offer_is_open_until_claimed() -> None:
    catalogue, _, _ = shop()
    trial, _, _, _ = build(catalogue)

    offer = await trial.offer(USER)

    assert offer.available
    assert offer.traffic_mib == TRIAL_TRAFFIC_MIB
    assert offer.duration_days == TRIAL_DURATION_DAYS


@pytest.mark.asyncio
async def test_a_tier_with_nothing_on_sale_is_skipped() -> None:
    tunnel = product(ProductTier.TUNNEL)
    hidden = product(ProductTier.DIRECT, published=False)
    catalogue = Catalogue(
        [tunnel, hidden],
        [plan(tunnel, days=30, price=1), plan(hidden, days=30, price=1)],
    )
    trial, _, _, _ = build(catalogue)

    placed = await trial.place(USER)

    assert [order.product_id for order in placed] == [str(tunnel.id)]


@pytest.mark.asyncio
async def test_no_plan_at_all_means_no_trial_and_no_claim() -> None:
    elite = product(ProductTier.ELITE)
    catalogue = Catalogue([elite], [plan(elite, days=30, price=1)])
    trial, claims, _, _ = build(catalogue)

    assert not (await trial.offer(USER)).available
    with pytest.raises(FreeTrialUnavailable):
        await trial.place(USER)
    # Nothing was given, so nothing is used up.
    assert claims.rows == {}


@pytest.mark.asyncio
async def test_a_panel_failure_leaves_the_order_owed_not_lost() -> None:
    catalogue, _, _ = shop()
    panel = FakePanel(fail_with=UNREACHABLE)
    trial, claims, orders, _ = build(catalogue, panel=panel)

    placed = await trial.place(USER)
    delivery = await trial.deliver(placed)

    assert delivery.subscriptions == ()
    assert delivery.pending == 2
    assert USER in claims.rows
    assert all(orders.rows[o.id].state is OrderState.FAILED for o in placed)
