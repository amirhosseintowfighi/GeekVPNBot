"""The Order aggregate: one purchase, from intent to a working account.

An order is deliberately separate from its invoice and its payment. The
invoice is what we are owed, the payment is how money moved, and the order is
what the customer expects to receive. Collapsing them was tempting until the
first partial refund, the first renewal, and the first "paid but the panel was
down" - each of which needs the three to disagree for a while.

A plan's terms are **copied onto the order**, never referenced. When the price
of a plan changes next month, an order placed today must still say what was
sold and for how much.
"""

from __future__ import annotations

from datetime import datetime

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning.enums import OrderSource, OrderState
from geekvpn.domain.provisioning.errors import (
    IllegalOrderTransition,
    OrderValidationError,
)
from geekvpn.domain.provisioning.events import (
    OrderCancelled,
    OrderFailed,
    OrderPaid,
    OrderPlaced,
    OrderProvisioned,
)

#: Allowed moves. Anything absent raises rather than silently no-ops, because
#: a double-approve must be visible, not absorbed.
_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.PENDING: frozenset({OrderState.PAID, OrderState.CANCELLED}),
    OrderState.PAID: frozenset(
        {
            OrderState.PROVISIONING,
            OrderState.FAILED,
            OrderState.REFUNDED,
            OrderState.CANCELLED,
        }
    ),
    OrderState.PROVISIONING: frozenset({OrderState.ACTIVE, OrderState.FAILED}),
    # A failed order can be retried: the money is already ours, and the fix is
    # usually another node rather than a refund.
    OrderState.FAILED: frozenset(
        {OrderState.PROVISIONING, OrderState.REFUNDED, OrderState.CANCELLED}
    ),
    OrderState.ACTIVE: frozenset({OrderState.REFUNDED}),
    OrderState.CANCELLED: frozenset(),
    OrderState.REFUNDED: frozenset(),
}


class Order(AggregateRoot[str]):
    """One purchase of one plan by one customer."""

    __slots__ = (
        "_state",
        "campaign_id",
        "coupon_code",
        "device_limit",
        "discount",
        "duration_days",
        "failure_reason",
        "invoice_id",
        "is_renewal",
        "list_price",
        "number",
        "paid_at",
        "placed_at",
        "plan_id",
        "plan_name_fa",
        "product_id",
        "provisioned_at",
        "renews_subscription_id",
        "source",
        "total",
        "traffic_mib",
        "user_id",
    )

    def __init__(
        self,
        order_id: str,
        *,
        number: str,
        user_id: int,
        plan_id: str,
        plan_name_fa: str,
        duration_days: int,
        list_price: Money,
        total: Money,
        placed_at: datetime,
        product_id: str | None = None,
        traffic_mib: int | None = None,
        device_limit: int = 2,
        discount: Money | None = None,
        state: OrderState = OrderState.PENDING,
        campaign_id: str | None = None,
        coupon_code: str | None = None,
        invoice_id: str | None = None,
        is_renewal: bool = False,
        renews_subscription_id: str | None = None,
        paid_at: datetime | None = None,
        provisioned_at: datetime | None = None,
        failure_reason: str | None = None,
        source: OrderSource = OrderSource.BOT,
    ) -> None:
        super().__init__(order_id)
        if duration_days <= 0:
            raise OrderValidationError(
                "An order must cover at least one day.", duration_days=duration_days
            )
        if traffic_mib is not None and traffic_mib <= 0:
            raise OrderValidationError(
                "Traffic must be positive, or None for an unlimited plan.",
                traffic_mib=traffic_mib,
            )
        self.number = number
        self.user_id = user_id
        self.plan_id = plan_id
        self.product_id = product_id
        self.plan_name_fa = plan_name_fa
        self.duration_days = duration_days
        self.traffic_mib = traffic_mib
        self.device_limit = device_limit
        self.list_price = list_price
        self.discount = discount or Money(0)
        self.total = total
        self._state = state
        self.campaign_id = campaign_id
        self.coupon_code = coupon_code
        self.invoice_id = invoice_id
        self.is_renewal = is_renewal
        self.renews_subscription_id = renews_subscription_id
        self.placed_at = placed_at
        self.paid_at = paid_at
        self.provisioned_at = provisioned_at
        self.failure_reason = failure_reason
        self.source = source

    # ---- Construction ---------------------------------------------------

    @classmethod
    def place(
        cls,
        order_id: str,
        *,
        number: str,
        user_id: int,
        plan_id: str,
        plan_name_fa: str,
        duration_days: int,
        list_price: Money,
        total: Money,
        now: datetime,
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
        order = cls(
            order_id,
            number=number,
            user_id=user_id,
            plan_id=plan_id,
            plan_name_fa=plan_name_fa,
            duration_days=duration_days,
            list_price=list_price,
            total=total,
            placed_at=now,
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
        order.record(
            OrderPlaced(
                order_id=order_id,
                number=number,
                user_id=user_id,
                plan_id=plan_id,
                total=total.amount,
                is_renewal=is_renewal,
            )
        )
        return order

    @classmethod
    def restore(cls, order_id: str, **fields: object) -> Order:
        """Rebuild from storage. Records nothing: loading is not an event."""
        return cls(order_id, **fields)  # type: ignore[arg-type]

    # ---- Accessors ------------------------------------------------------

    @property
    def state(self) -> OrderState:
        return self._state

    @property
    def is_unlimited(self) -> bool:
        return self.traffic_mib is None

    @property
    def savings(self) -> Money:
        return self.list_price - self.total

    def can_transition_to(self, target: OrderState) -> bool:
        return target in _TRANSITIONS[self._state]

    def _move(self, target: OrderState) -> None:
        if not self.can_transition_to(target):
            raise IllegalOrderTransition(current=self._state.value, target=target.value)
        self._state = target

    # ---- Transitions ----------------------------------------------------

    def mark_paid(self, *, at: datetime, invoice_id: str | None = None) -> None:
        self._move(OrderState.PAID)
        self.paid_at = at
        if invoice_id is not None:
            self.invoice_id = invoice_id
        self.record(OrderPaid(order_id=self.id, user_id=self.user_id, total=self.total.amount))

    def start_provisioning(self) -> None:
        self._move(OrderState.PROVISIONING)
        # Cleared on every attempt so a stale reason from a previous failure
        # cannot be shown next to a successful account.
        self.failure_reason = None

    def mark_active(self, *, subscription_id: str, at: datetime) -> None:
        self._move(OrderState.ACTIVE)
        self.provisioned_at = at
        self.failure_reason = None
        self.record(
            OrderProvisioned(
                order_id=self.id,
                user_id=self.user_id,
                subscription_id=subscription_id,
            )
        )

    def fail(self, *, reason: str) -> None:
        self._move(OrderState.FAILED)
        self.failure_reason = reason
        self.record(OrderFailed(order_id=self.id, user_id=self.user_id, reason=reason))

    def cancel(self) -> None:
        self._move(OrderState.CANCELLED)
        self.record(OrderCancelled(order_id=self.id, user_id=self.user_id))

    def mark_refunded(self) -> None:
        self._move(OrderState.REFUNDED)


__all__ = ["Order"]
