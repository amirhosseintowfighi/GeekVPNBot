"""Provisioning: the step that turns money into a working account."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.provisioning.provisioning_service import (
    ProvisioningService,
    username_for,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning.enums import OrderState, SubscriptionState
from geekvpn.domain.provisioning.errors import (
    NoCapacityAvailable,
    OrderNotFound,
    ProvisioningFailed,
)
from geekvpn.domain.provisioning.order import Order
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
    node,
)

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def paid_order(
    *,
    order_id: str = "ord-1",
    number: str = "1405-0001",
    traffic_mib: int | None = 50 * 1024,
    duration_days: int = 30,
) -> Order:
    order = Order.place(
        order_id,
        number=number,
        user_id=777,
        plan_id="plan-1",
        plan_name_fa="پلن ۵۰ گیگ",
        duration_days=duration_days,
        list_price=Money(300_000),
        total=Money(250_000),
        now=NOW,
        traffic_mib=traffic_mib,
        device_limit=3,
    )
    order.mark_paid(at=NOW, invoice_id="inv-1")
    order.collect_events()
    return order


def build(
    order: Order,
    *,
    panel: FakePanel | None = None,
    nodes: InMemoryNodes | None = None,
) -> tuple[
    ProvisioningService, InMemoryOrders, InMemorySubscriptions, FakePanel, RecordingPublisher
]:
    orders = InMemoryOrders(order)
    subscriptions = InMemorySubscriptions()
    panel = panel or FakePanel()
    events = RecordingPublisher()
    service = ProvisioningService(
        orders=orders,
        subscriptions=subscriptions,
        nodes=nodes or InMemoryNodes(node("node-de")),
        panels=FakePanelProvider(panel),
        clock=FrozenClock(NOW),
        ids=SequentialIds("sub"),
        events=events,
    )
    return service, orders, subscriptions, panel, events


# -- the happy path --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_paid_order_becomes_an_active_subscription() -> None:
    order = paid_order()
    service, orders, subscriptions, panel, _events = build(order)

    subscription = await service.provision(order.id)

    assert subscription.state is SubscriptionState.ACTIVE
    assert orders.rows[order.id].state is OrderState.ACTIVE
    assert subscriptions.rows[subscription.id].order_id == order.id
    assert len(panel.created) == 1


@pytest.mark.asyncio
async def test_the_order_terms_are_carried_onto_the_panel() -> None:
    order = paid_order(traffic_mib=50 * 1024, duration_days=30)
    service, _, _, panel, _ = build(order)

    await service.provision(order.id)
    spec = panel.created[0]

    assert spec.quota.total_bytes == 50 * 1024 * 1024 * 1024
    assert spec.expires_at == NOW + timedelta(days=30)
    assert spec.device_limit == 3


@pytest.mark.asyncio
async def test_an_unlimited_plan_is_uncapped_not_zero_capped() -> None:
    """The bug this pins would give every unlimited customer zero bytes."""
    order = paid_order(traffic_mib=None)
    service, _, _subscriptions, panel, _ = build(order)

    subscription = await service.provision(order.id)

    assert panel.created[0].quota.is_unlimited
    assert subscription.is_unlimited


@pytest.mark.asyncio
async def test_the_subscription_records_where_it_lives() -> None:
    order = paid_order()
    service, _, _, _panel, _ = build(order)

    subscription = await service.provision(order.id)

    assert subscription.node_id == "node-de"
    assert subscription.remote_username == username_for(order)
    assert subscription.subscription_url is not None


@pytest.mark.asyncio
async def test_it_publishes_the_provisioned_and_activated_events() -> None:
    order = paid_order()
    service, _, _, _, events = build(order)

    await service.provision(order.id)

    assert "OrderProvisioned" in events.names()
    assert "SubscriptionActivated" in events.names()


# -- idempotency -----------------------------------------------------------


@pytest.mark.asyncio
async def test_the_panel_username_is_derived_so_a_retry_asks_for_the_same_one() -> None:
    order = paid_order(number="1405-0042")

    assert username_for(order) == "gv14050042"
    assert username_for(order) == username_for(order)


@pytest.mark.asyncio
async def test_provisioning_twice_does_not_create_a_second_account() -> None:
    order = paid_order()
    service, _, subscriptions, panel, _ = build(order)

    first = await service.provision(order.id)
    second = await service.provision(order.id)

    assert first.id == second.id
    assert len(subscriptions.rows) == 1
    assert len(panel.created) == 1


@pytest.mark.asyncio
async def test_the_order_id_is_the_idempotency_key() -> None:
    order = paid_order()
    service, _, _, panel, _ = build(order)

    await service.provision(order.id)

    assert panel.idempotency_keys == [order.id]


@pytest.mark.asyncio
async def test_a_subscription_without_an_active_order_repairs_the_order() -> None:
    """The crash-between-writes case: the customer has service, the order lies."""
    order = paid_order()
    service, orders, _subscriptions, _, _ = build(order)
    subscription = await service.provision(order.id)

    # Simulate the order update having been lost.
    orders.rows[order.id]._state = OrderState.PROVISIONING

    recovered = await service.provision(order.id)

    assert recovered.id == subscription.id
    assert orders.rows[order.id].state is OrderState.ACTIVE


# -- failure ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_order_is_an_error_not_a_silent_no_op() -> None:
    service, *_ = build(paid_order())

    with pytest.raises(OrderNotFound):
        await service.provision("does-not-exist")


@pytest.mark.asyncio
async def test_an_unreachable_panel_leaves_the_order_failed_not_refunded() -> None:
    order = paid_order()
    service, orders, subscriptions, _, _ = build(order, panel=FakePanel(fail_with=UNREACHABLE))

    with pytest.raises(ProvisioningFailed):
        await service.provision(order.id)

    assert orders.rows[order.id].state is OrderState.FAILED
    assert orders.rows[order.id].failure_reason is not None
    assert subscriptions.rows == {}


@pytest.mark.asyncio
async def test_no_capacity_fails_the_order_with_its_own_reason() -> None:
    order = paid_order()
    service, orders, _, _, _ = build(
        order, nodes=InMemoryNodes(node("full", capacity=5, account_count=5))
    )

    with pytest.raises(NoCapacityAvailable):
        await service.provision(order.id)

    assert orders.rows[order.id].failure_reason == "no_capacity_available"


@pytest.mark.asyncio
async def test_a_failed_order_can_be_retried_onto_a_working_panel() -> None:
    order = paid_order()
    service, orders, _, _, _ = build(order, panel=FakePanel(fail_with=UNREACHABLE))
    with pytest.raises(ProvisioningFailed):
        await service.provision(order.id)

    healthy = FakePanel()
    retry, _, _subscriptions, _, _ = build(orders.rows[order.id], panel=healthy)
    subscription = await retry.provision(order.id)

    assert subscription.state is SubscriptionState.ACTIVE
    assert len(healthy.created) == 1


# -- the retry queue -------------------------------------------------------


@pytest.mark.asyncio
async def test_the_sweep_keeps_going_after_one_order_fails() -> None:
    """One dead panel must not stop the sweep fixing everything else."""
    good = paid_order(order_id="ok", number="1405-0001")
    orders = InMemoryOrders(good)
    subscriptions = InMemorySubscriptions()
    events = RecordingPublisher()
    service = ProvisioningService(
        orders=orders,
        subscriptions=subscriptions,
        nodes=InMemoryNodes(node("node-de")),
        panels=FakePanelProvider(FakePanel()),
        clock=FrozenClock(NOW + timedelta(minutes=5)),
        ids=SequentialIds("sub"),
        events=events,
    )

    done = await service.drain_stuck(older_than_seconds=60)

    assert done == ("ok",)
