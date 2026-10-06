"""A coupon is spent when the order is placed, so an order that is never paid
must hand it back.

The redemption is recorded at placement on purpose: two checkouts racing
through a single-use code must not both get the discount. But nothing undid
it. A receipt the operator rejected, a gateway attempt that died, a proof
window that closed - each left the order PENDING forever and the code burnt,
and a customer with a one-time code who mistyped a card number lost the code
along with the purchase.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from geekvpn.application.provisioning.order_service import UnpaidOrderRelease
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning.enums import OrderState
from geekvpn.domain.provisioning.order import Order

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)


class Publisher:
    def __init__(self) -> None:
        self.names: list[str] = []

    def publish_all(self, events: object) -> None:
        self.names.extend(getattr(e, "name", "") for e in events)  # type: ignore[attr-defined]


class Orders:
    def __init__(self, order: Order) -> None:
        self.order = order

    def get_by_invoice(self, invoice_id: str) -> Order | None:
        return self.order if self.order.invoice_id == invoice_id else None

    def get(self, order_id: str) -> Order | None:
        return self.order if self.order.id == order_id else None

    def update(self, order: Order) -> None:
        return None


class Coupons:
    def __init__(self) -> None:
        self.released: list[tuple[str, str]] = []

    def release(self, *, code: str, order_id: str) -> None:
        self.released.append((code, order_id))


class Rejected:
    """Just enough of `PaymentRejected` for the loosely-typed handler."""

    def __init__(self, payment_id: str) -> None:
        self.payment_id = payment_id


def make_order(*, coupon: str | None = "SPRING") -> Order:
    order = Order.place(
        uuid.uuid4().hex,
        number="1405-00042",
        user_id=87791922,
        plan_id=str(uuid.uuid4()),
        plan_name_fa="آلمان",
        duration_days=30,
        list_price=Money(200_000),
        total=Money(150_000),
        discount=Money(50_000),
        coupon_code=coupon,
        now=NOW,
    )
    order.invoice_id = "inv-1"
    return order


def build(order: Order) -> tuple[UnpaidOrderRelease, Coupons, Publisher]:
    coupons = Coupons()
    publisher = Publisher()
    release = UnpaidOrderRelease(
        orders=Orders(order),
        coupons=coupons,
        events=publisher,
        invoice_for_payment=lambda payment_id: "inv-1" if payment_id == "pay-1" else None,
    )
    return release, coupons, publisher


def test_a_rejected_payment_gives_the_coupon_back() -> None:
    order = make_order()
    release, coupons, _ = build(order)

    release.on_payment_abandoned(Rejected("pay-1"))

    assert coupons.released == [("SPRING", order.id)]


def test_a_rejected_payment_cancels_its_order() -> None:
    """Left PENDING, the order would sit in the stuck queue forever."""
    order = make_order()
    release, _, publisher = build(order)

    release.on_payment_abandoned(Rejected("pay-1"))

    assert order.state is OrderState.CANCELLED
    assert "provisioning.order.cancelled.v1" in publisher.names


def test_an_order_without_a_coupon_releases_nothing() -> None:
    order = make_order(coupon=None)
    release, coupons, _ = build(order)

    release.on_payment_abandoned(Rejected("pay-1"))

    assert coupons.released == []
    assert order.state is OrderState.CANCELLED


def test_a_paid_order_keeps_its_coupon() -> None:
    """A late rejection event for an order already paid by another payment
    must not refund the discount the customer actually used."""
    order = make_order()
    order.mark_paid(at=NOW, invoice_id="inv-1")
    release, coupons, _ = build(order)

    release.on_payment_abandoned(Rejected("pay-1"))

    assert coupons.released == []
    assert order.state is OrderState.PAID


def test_a_payment_that_bought_nothing_is_absorbed() -> None:
    """A rejected wallet top-up has no order, and that is not an error."""
    order = make_order()
    release, coupons, _ = build(order)

    release.on_payment_abandoned(Rejected("pay-other"))

    assert coupons.released == []
    assert order.state is OrderState.PENDING
