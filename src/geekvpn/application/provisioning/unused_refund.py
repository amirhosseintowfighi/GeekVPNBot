"""Giving the money back for a service that was never used.

A customer who bought the wrong plan, or on the wrong server, and has not
sent a single byte through it can return it within the shop's window and get
the price back into their wallet. Into the wallet and not to a card: the
money stays in the shop, and nobody has to make a bank transfer by hand.

"Never used" is the panel's answer, not ours. The stored counter can be an
hour old, so usage is read from the panel first; a service the customer
started using in the last hour must not slip through on a stale zero.

The order matters. The panel account is deleted first, so a refunded service
cannot keep working; then the wallet is credited; then the order is marked
refunded. If the credit fails the service is already revoked, which refuses
any retry - better than a second refund - and the operator sees both the
revoked service and the failure in the log.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta

from geekvpn.application.ports.clock import Clock
from geekvpn.application.provisioning.ports import OrderRepository, SubscriptionRepository
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning.enums import OrderSource, SubscriptionState
from geekvpn.domain.provisioning.errors import RefundNotAllowed
from geekvpn.domain.provisioning.subscription import Subscription

REFUND_REASON_FA = "برگشت وجه سرویس استفاده‌نشده"


class UnusedRefund:
    def __init__(
        self,
        *,
        subscriptions: SubscriptionRepository,
        orders: OrderRepository,
        refresh_usage: Callable[[str], Awaitable[Subscription | None]],
        revoke: Callable[[str, str], Awaitable[Subscription]],
        credit: Callable[[int, Money, str], Awaitable[None]],
        window: Callable[[], Awaitable[int]],
        clock: Clock,
    ) -> None:
        self._subscriptions = subscriptions
        self._orders = orders
        self._refresh_usage = refresh_usage
        self._revoke = revoke
        self._credit = credit
        #: Hours after purchase a refund may be asked for; 0 turns it off.
        self._window = window
        self._clock = clock

    async def refund(self, subscription_id: str, *, owner: int) -> Money:
        """Revoke the service and credit its price. Returns what was credited.

        :raises RefundNotAllowed: with the reason in Persian, for every case
            in which the answer is no.
        """
        hours = await self._window()
        if hours <= 0:
            raise RefundNotAllowed("برگشت وجه در این فروشگاه فعال نیست.")
        subscription = await self._subscriptions.get(subscription_id)
        if subscription is None or subscription.user_id != owner:
            raise RefundNotAllowed("این سرویس پیدا نشد.")
        if subscription.state is not SubscriptionState.ACTIVE:
            raise RefundNotAllowed("فقط سرویس فعال قابل برگشت وجهه.")
        if self._clock.now() - subscription.started_at > timedelta(hours=hours):
            raise RefundNotAllowed(f"مهلت برگشت وجه ({hours} ساعت بعد از خرید) تموم شده.")
        order = await self._orders.get(subscription.order_id) if subscription.order_id else None
        if order is None or order.source is OrderSource.TRIAL or order.total.amount <= 0:
            raise RefundNotAllowed("این سرویس خریداری نشده که وجهش برگرده.")

        fresh = await self._refresh_usage(subscription_id) or subscription
        if fresh.traffic_used_mib > 0:
            raise RefundNotAllowed("این سرویس استفاده شده و وجهش برنمی‌گرده.")

        await self._revoke(subscription_id, REFUND_REASON_FA)
        await self._credit(owner, order.total, order.number)
        order.mark_refunded()
        await self._orders.update(order)
        return order.total


__all__ = ["REFUND_REASON_FA", "UnusedRefund"]
