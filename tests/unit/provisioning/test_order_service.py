"""Order placement, and the bridge that moves an order to PAID."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from geekvpn.application.provisioning.order_service import (
    OrderPaymentBridge,
    OrderService,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning.enums import OrderState
from geekvpn.domain.provisioning.errors import OrderNotFound
from geekvpn.domain.provisioning.order import Order
from tests.unit.provisioning.fakes import (
    FrozenClock,
    InMemoryOrders,
    RecordingPublisher,
    SequentialIds,
    SequentialNumbers,
    SyncOrders,
)

NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


class _Approved:
    """Stands in for ``PaymentApproved`` without importing the billing module."""

    def __init__(self, invoice_id: str) -> None:
        self.invoice_id = invoice_id


def build_service() -> tuple[OrderService, InMemoryOrders, RecordingPublisher]:
    orders = InMemoryOrders()
    events = RecordingPublisher()
    service = OrderService(
        orders=orders,
        clock=FrozenClock(NOW),
        ids=SequentialIds("ord"),
        numbers=SequentialNumbers(),
        events=events,
    )
    return service, orders, events


async def place(service: OrderService) -> Order:
    return await service.place(
        user_id=777,
        jalali_year=1405,
        plan_id="plan-1",
        plan_name_fa="پلن ۵۰ گیگ",
        duration_days=30,
        list_price=Money(300_000),
        total=Money(250_000),
        traffic_mib=50 * 1024,
    )


# -- placement -------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_order_starts_pending_and_is_persisted() -> None:
    service, orders, _ = build_service()

    order = await place(service)

    assert order.state is OrderState.PENDING
    assert orders.rows[order.id] is order


@pytest.mark.asyncio
async def test_the_terms_are_copied_onto_the_order_not_referenced() -> None:
    """A price change next month must not rewrite what was sold today."""
    service, _, _ = build_service()

    order = await place(service)

    assert order.total == Money(250_000)
    assert order.list_price == Money(300_000)
    assert order.savings == Money(50_000)
    assert order.plan_name_fa == "پلن ۵۰ گیگ"


@pytest.mark.asyncio
async def test_placing_publishes_the_placed_event() -> None:
    service, _, events = build_service()

    await place(service)

    assert events.names() == ["OrderPlaced"]


@pytest.mark.asyncio
async def test_cancelling_an_unknown_order_raises() -> None:
    service, _, _ = build_service()

    with pytest.raises(OrderNotFound):
        await service.cancel("nope")


@pytest.mark.asyncio
async def test_an_unpaid_order_can_be_cancelled() -> None:
    service, orders, _ = build_service()
    order = await place(service)

    cancelled = await service.cancel(order.id)

    assert cancelled.state is OrderState.CANCELLED
    assert orders.rows[order.id].state is OrderState.CANCELLED


# -- the payment bridge ----------------------------------------------------


def build_bridge(*orders: Order) -> tuple[OrderPaymentBridge, SyncOrders, RecordingPublisher]:
    repo = SyncOrders(*orders)
    events = RecordingPublisher()
    bridge = OrderPaymentBridge(orders=repo, clock=FrozenClock(NOW), events=events)
    return bridge, repo, events


def pending_order(order_id: str = "ord-1") -> Order:
    order = Order.place(
        order_id,
        number="1405-0001",
        user_id=777,
        plan_id="plan-1",
        plan_name_fa="پلن",
        duration_days=30,
        list_price=Money(250_000),
        total=Money(250_000),
        now=NOW,
    )
    order.collect_events()
    return order


def test_approval_moves_the_order_to_paid() -> None:
    order = pending_order()
    bridge, repo, events = build_bridge(order)
    repo.link("inv-1", order.id)

    result = bridge.on_payment_approved(_Approved("inv-1"))

    assert result is not None
    assert result.state is OrderState.PAID
    assert result.invoice_id == "inv-1"
    assert result.paid_at == NOW
    assert "OrderPaid" in events.names()


def test_a_wallet_topup_buys_nothing_and_is_not_an_error() -> None:
    bridge, _, events = build_bridge()

    assert bridge.on_payment_approved(_Approved("inv-topup")) is None
    assert events.events == []


def test_a_duplicate_approval_is_absorbed_not_raised() -> None:
    """Raising here would roll back a legitimate payment approval."""
    order = pending_order()
    bridge, repo, _ = build_bridge(order)
    repo.link("inv-1", order.id)
    bridge.on_payment_approved(_Approved("inv-1"))

    again = bridge.on_payment_approved(_Approved("inv-1"))

    assert again is not None
    assert again.state is OrderState.PAID


def test_an_event_without_an_invoice_is_ignored() -> None:
    bridge, _, _ = build_bridge()

    assert bridge.on_payment_approved(object()) is None
