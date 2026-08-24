"""Placing an order, and moving it to PAID when the money lands.

An order is created *before* checkout, not after, and its id travels on the
invoice metadata. That ordering is the whole point: if the process dies between
taking money and recording what was bought, the order already exists and the
retry queue finds it. The reverse ordering loses the purchase entirely.

Two classes live here because they run in two different scopes:

* :class:`OrderService` is asynchronous and runs in the API request scope
  alongside the catalog.
* :class:`OrderPaymentBridge` is synchronous, because payment approval runs in
  the synchronous scope, and the order must move to PAID inside the same
  transaction that approves the payment.
"""

from __future__ import annotations

from collections.abc import Callable

from geekvpn.application.ports.clock import Clock
from geekvpn.application.provisioning.ports import (
    EventPublisher,
    IdGenerator,
    OrderNumberGenerator,
    OrderRepository,
    SyncOrderRepository,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning.enums import OrderSource, OrderState
from geekvpn.domain.provisioning.errors import OrderNotFound
from geekvpn.domain.provisioning.order import Order

#: Key under which the order id is carried on the invoice, so that payment
#: approval can find its way back without payments importing provisioning.
INVOICE_ORDER_KEY = "order_id"


class OrderService:
    """Creates orders. Knows nothing about how they will be paid for."""

    __slots__ = ("_clock", "_events", "_ids", "_numbers", "_orders")

    def __init__(
        self,
        *,
        orders: OrderRepository,
        clock: Clock,
        ids: IdGenerator,
        numbers: OrderNumberGenerator,
        events: EventPublisher,
    ) -> None:
        self._orders = orders
        self._clock = clock
        self._ids = ids
        self._numbers = numbers
        self._events = events

    async def place(
        self,
        *,
        user_id: int,
        jalali_year: int,
        plan_id: str,
        plan_name_fa: str,
        duration_days: int,
        list_price: Money,
        total: Money,
        product_id: str | None = None,
        traffic_mib: int | None = None,
        device_limit: int = 2,
        discount: Money | None = None,
        campaign_id: str | None = None,
        coupon_code: str | None = None,
        is_renewal: bool = False,
        renews_subscription_id: str | None = None,
        source: OrderSource = OrderSource.BOT,
    ) -> Order:
        """Record what the customer is buying, at today's terms.

        The plan's terms are copied onto the order rather than referenced, so a
        price change next month cannot rewrite what was sold today.
        """
        order = Order.place(
            self._ids.new_id(),
            number=await self._numbers.next_number(jalali_year=jalali_year),
            user_id=user_id,
            plan_id=plan_id,
            plan_name_fa=plan_name_fa,
            duration_days=duration_days,
            list_price=list_price,
            total=total,
            now=self._clock.now(),
            product_id=product_id,
            traffic_mib=traffic_mib,
            device_limit=device_limit,
            discount=discount,
            campaign_id=campaign_id,
            coupon_code=coupon_code,
            is_renewal=is_renewal,
            renews_subscription_id=renews_subscription_id,
            source=source,
        )
        await self._orders.add(order)
        self._events.publish_all(order.collect_events())
        return order

    async def cancel(self, order_id: str) -> Order:
        """Abandon an unpaid order. Paid orders must be refunded, not cancelled."""
        order = await self._orders.get(order_id)
        if order is None:
            raise OrderNotFound("The order was not found.", order_id=order_id)
        order.cancel()
        await self._orders.update(order)
        self._events.publish_all(order.collect_events())
        return order


class OrderPaymentBridge:
    """Moves an order to PAID when its payment is approved.

    Subscribed to ``billing.payment.approved.v1``, which the payment domain
    documents as the single trigger for provisioning. Nothing else in the system
    is allowed to start a subscription, so nothing else calls this.

    Returns ``None`` rather than raising when the invoice has no order: wallet
    top-ups are payments too, and they legitimately buy nothing.
    """

    __slots__ = ("_clock", "_events", "_order_id_for_invoice", "_orders")

    def __init__(
        self,
        *,
        orders: SyncOrderRepository,
        clock: Clock,
        events: EventPublisher,
        order_id_for_invoice: Callable[[str], str | None] | None = None,
    ) -> None:
        self._orders = orders
        self._clock = clock
        self._events = events
        # A second way to find the order, for the window where the first one
        # cannot work. See `_find_order`.
        self._order_id_for_invoice = order_id_for_invoice

    def on_payment_approved(self, event: object) -> Order | None:
        """Handle ``PaymentApproved``.

        Typed loosely on purpose: binding this signature to the payments module
        would make provisioning depend on billing, and the direction of that
        dependency is the reason a Telegram outage cannot roll back a payment.
        """
        invoice_id = getattr(event, "invoice_id", None)
        if not isinstance(invoice_id, str):
            return None

        order = self._find_order(invoice_id)
        if order is None:
            return None
        if order.state is not OrderState.PENDING:
            # Re-approval, or an operator approving an already-paid payment.
            # Absorbing it here is correct; the transition guard would raise and
            # roll back a legitimate payment approval over a duplicate event.
            return order

        order.mark_paid(at=self._clock.now(), invoice_id=invoice_id)
        self._orders.update(order)
        self._events.publish_all(order.collect_events())
        return order

    def _find_order(self, invoice_id: str) -> Order | None:
        """By invoice, or by the order id the invoice was created with.

        The second path exists because of a window the first cannot cover. A
        wallet purchase settles *inside* the call that creates the invoice, so
        this handler runs before the caller has had a chance to write the
        invoice id onto the order - `get_by_invoice` matches nothing, the order
        stays PENDING, and provisioning then refuses it, because PENDING to
        PROVISIONING is not a legal transition. The customer is debited and
        receives nothing.

        The order id has been travelling on the invoice's metadata the whole
        time: `INVOICE_ORDER_KEY` was defined and exported for exactly this and
        never read by anything.

        A callable rather than the invoice repository, so provisioning still
        does not depend on billing - the direction of that dependency is why a
        Telegram outage cannot roll back a payment.
        """
        order = self._orders.get_by_invoice(invoice_id)
        if order is not None:
            return order
        if self._order_id_for_invoice is None:
            return None
        order_id = self._order_id_for_invoice(invoice_id)
        return self._orders.get(order_id) if order_id else None


__all__ = ["INVOICE_ORDER_KEY", "OrderPaymentBridge", "OrderService"]
