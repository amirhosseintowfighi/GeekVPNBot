"""A wallet purchase settles before its order can be linked to the invoice.

`OrderPaymentBridge` finds the order by invoice id. That works for a card
payment, which is approved minutes later by an operator, by which time the
caller has written the invoice id onto the order.

It cannot work for a wallet payment. That one settles *inside* the call that
creates the invoice, so the handler runs first: `get_by_invoice` matches
nothing, the order stays PENDING, and provisioning then refuses it - PENDING to
PROVISIONING is not a legal transition. The customer is debited and receives
nothing, which is exactly what happened.

The order id was on the invoice's metadata the whole time. `INVOICE_ORDER_KEY`
was defined and exported for this and read by nothing.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from geekvpn.application.provisioning.order_service import (
    INVOICE_ORDER_KEY,
    OrderPaymentBridge,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning.enums import OrderState
from geekvpn.domain.provisioning.order import Order

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 24, 17, 0, tzinfo=UTC)


class FrozenClock:
    def now(self) -> datetime:
        return NOW


class Publisher:
    def publish_all(self, events: object) -> None:
        return None


class Orders:
    """A sync order repository whose invoice link is not written yet."""

    def __init__(self, order: Order) -> None:
        self.order = order
        self.updated = 0

    def get_by_invoice(self, invoice_id: str) -> Order | None:
        return self.order if self.order.invoice_id == invoice_id else None

    def get(self, order_id: str) -> Order | None:
        return self.order if self.order.id == order_id else None

    def update(self, order: Order) -> None:
        self.updated += 1


class Approved:
    """Just enough of `PaymentApproved` for the loosely-typed handler."""

    def __init__(self, invoice_id: str) -> None:
        self.invoice_id = invoice_id


def make_order() -> Order:
    return Order.place(
        uuid.uuid4().hex,
        number="1405-00007",
        user_id=87791922,
        plan_id=str(uuid.uuid4()),
        plan_name_fa="آلمان",
        duration_days=30,
        list_price=Money(200_000),
        total=Money(200_000),
        now=NOW,
    )


def build(order: Order, *, metadata: dict[str, str] | None = None):
    orders = Orders(order)
    bridge = OrderPaymentBridge(
        orders=orders,
        clock=FrozenClock(),
        events=Publisher(),
        order_id_for_invoice=(lambda _: (metadata or {}).get(INVOICE_ORDER_KEY)),
    )
    return bridge, orders


def test_an_order_already_linked_to_its_invoice_is_still_found() -> None:
    """The card path, which was never broken and must stay that way."""
    order = make_order()
    order.invoice_id = "inv-1"
    bridge, orders = build(order)

    assert bridge.on_payment_approved(Approved("inv-1")) is not None
    assert order.state is OrderState.PAID
    assert orders.updated == 1


def test_an_unlinked_order_is_found_through_the_invoice_metadata() -> None:
    """The wallet path: the bug this exists for."""
    order = make_order()
    bridge, _ = build(order, metadata={INVOICE_ORDER_KEY: order.id})

    assert bridge.on_payment_approved(Approved("inv-1")) is not None
    assert order.state is OrderState.PAID


def test_a_payment_that_bought_nothing_is_absorbed() -> None:
    """A wallet top-up is a payment too, and legitimately has no order."""
    order = make_order()
    bridge, _ = build(order, metadata={})

    assert bridge.on_payment_approved(Approved("inv-1")) is None
    assert order.state is OrderState.PENDING


def test_provisioning_needs_the_paid_state_this_produces() -> None:
    """Why the missed link was fatal rather than cosmetic."""
    order = make_order()

    assert not order.can_transition_to(OrderState.PROVISIONING)
    order.mark_paid(at=NOW, invoice_id="inv-1")
    assert order.can_transition_to(OrderState.PROVISIONING)
