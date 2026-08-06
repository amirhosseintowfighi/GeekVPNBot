"""Turning a paid order into a working account.

This is the step the platform exists to perform, and it is a distributed
transaction across our database and somebody else's panel, over a network that
drops responses. Three decisions follow from that and they are the reason this
module looks the way it does:

**The panel username is derived, never generated.** It is a pure function of
the order number, so a retry after a dropped response asks the panel for the
same username, and the adapter contract says creating an account that already
matches returns the existing one. Random usernames would turn every timeout
into a duplicate account nobody is billing for.

**The order is the source of truth for "did this happen", not the panel.** A
subscription row already attached to the order short-circuits the whole
routine. That is what makes ``provision`` safe to call from a webhook, a retry
loop and an operator's "try again" button at the same moment.

**Failure is not a refund.** A panel being unreachable leaves the order in
FAILED, which the retry queue picks up again. The money stays captured because
the customer still wants the product; a human decides to refund, and only after
looking.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from geekvpn.application.ports.clock import Clock
from geekvpn.application.provisioning.node_selector import select_node
from geekvpn.application.provisioning.ports import (
    EventPublisher,
    IdGenerator,
    NodeRecord,
    NodeRepository,
    OrderRepository,
    PanelProvider,
    SubscriptionRepository,
)
from geekvpn.domain.panels.errors import PanelError
from geekvpn.domain.panels.values import AccountSpec, PanelAccountRef, TrafficQuota
from geekvpn.domain.provisioning.enums import OrderState
from geekvpn.domain.provisioning.errors import (
    NoCapacityAvailable,
    OrderNotFound,
    ProvisioningFailed,
    SubscriptionNotFound,
)
from geekvpn.domain.provisioning.order import Order
from geekvpn.domain.provisioning.subscription import Subscription

BYTES_PER_MIB = 1024 * 1024

#: Prefix on every panel username we own, so an operator looking at a panel can
#: tell our accounts from ones created by hand before this platform existed.
USERNAME_PREFIX = "gv"


def username_for(order: Order) -> str:
    """The panel username this order will always ask for.

    Derived from the order *number* rather than the id: it is short, it is what
    the customer quotes to support, and matching a complaint to a panel account
    should not require a database lookup.
    """
    cleaned = "".join(ch for ch in order.number if ch.isalnum()).lower()
    return f"{USERNAME_PREFIX}{cleaned}"


class ProvisioningService:
    """Creates and renews panel accounts for paid orders."""

    __slots__ = (
        "_clock",
        "_events",
        "_ids",
        "_nodes",
        "_orders",
        "_panels",
        "_subscriptions",
    )

    def __init__(
        self,
        *,
        orders: OrderRepository,
        subscriptions: SubscriptionRepository,
        nodes: NodeRepository,
        panels: PanelProvider,
        clock: Clock,
        ids: IdGenerator,
        events: EventPublisher,
    ) -> None:
        self._orders = orders
        self._subscriptions = subscriptions
        self._nodes = nodes
        self._panels = panels
        self._clock = clock
        self._ids = ids
        self._events = events

    # -- the main path -----------------------------------------------------

    async def provision(self, order_id: str, *, country_code: str | None = None) -> Subscription:
        """Deliver the service for one paid order.

        Idempotent: calling it twice for the same order returns the same
        subscription and touches the panel at most once more (the adapter's own
        idempotency handles the rest).

        :param order_id: the order to fulfil.
        :param country_code: restricts node selection when the plan promised a
            specific country.
        :raises OrderNotFound: no such order.
        :raises ProvisioningFailed: the panel refused or was unreachable. The
            order is left in FAILED for the retry queue.
        :raises NoCapacityAvailable: nothing to provision onto right now.
        """
        order = await self._orders.get(order_id)
        if order is None:
            raise OrderNotFound("The order was not found.", order_id=order_id)

        existing = await self._subscriptions.get_by_order(order.id)
        if existing is not None:
            # Already delivered. Repair the order state if a previous attempt
            # died between writing the subscription and updating the order,
            # then answer with what the customer actually has.
            if order.state is not OrderState.ACTIVE:
                order.mark_active(subscription_id=existing.id, at=self._clock.now())
                await self._orders.update(order)
                self._publish(order)
            return existing

        if order.is_renewal:
            return await self._renew(order)

        order.start_provisioning()
        await self._orders.update(order)

        now = self._clock.now()
        try:
            node = select_node(await self._nodes.list_sellable(), country_code=country_code)
        except NoCapacityAvailable:
            # Not a panel failure, and worth a distinct reason on the order so
            # the operator sees "add capacity", not "debug the adapter".
            await self._fail(order, reason="no_capacity_available")
            raise

        username = username_for(order)
        spec = AccountSpec(
            username=username,
            quota=_quota_for(order.traffic_mib),
            expires_at=now + timedelta(days=order.duration_days),
            device_limit=order.device_limit,
            note=f"order:{order.number}",
        )

        try:
            adapter = await self._panels.for_node(node)
            account = await adapter.create_account(spec, idempotency_key=order.id)
        except PanelError as error:
            await self._fail(order, reason=error.code)
            raise ProvisioningFailed(error.code, retryable=error.retryable) from error

        subscription = Subscription.activate(
            self._ids.new_id(),
            user_id=order.user_id,
            order_id=order.id,
            plan_id=order.plan_id,
            remote_username=account.ref.username,
            now=now,
            duration_days=order.duration_days,
            traffic_limit_mib=order.traffic_mib,
            device_limit=order.device_limit,
            node_id=node.id,
            remote_id=account.ref.external_id,
            subscription_url=account.subscription_url,
        )
        await self._subscriptions.add(subscription)

        order.mark_active(subscription_id=subscription.id, at=now)
        await self._orders.update(order)

        self._publish(order, subscription)
        return subscription

    # -- renewal -----------------------------------------------------------

    async def _renew(self, order: Order) -> Subscription:
        """Extend an existing account rather than issuing a second one.

        A renewal that created a new account would hand the customer new config
        to install every month, which is the single most common reason people
        stop renewing.
        """
        if order.renews_subscription_id is None:
            await self._fail(order, reason="renewal_without_subscription")
            raise ProvisioningFailed("renewal_without_subscription", retryable=False)

        subscription = await self._subscriptions.get(order.renews_subscription_id)
        if subscription is None:
            await self._fail(order, reason="subscription_not_found")
            raise SubscriptionNotFound(
                "The subscription being renewed no longer exists.",
                subscription_id=order.renews_subscription_id,
            )

        order.start_provisioning()
        await self._orders.update(order)

        now = self._clock.now()
        node = await self._nodes.get(subscription.node_id or "")
        if node is None:
            await self._fail(order, reason="node_not_found")
            raise ProvisioningFailed("node_not_found", retryable=False)

        try:
            adapter = await self._panels.for_node(node)
            await adapter.renew(
                _ref_for(subscription, node),
                extend_by=timedelta(days=order.duration_days),
                new_quota=_quota_for(order.traffic_mib),
                idempotency_key=order.id,
            )
        except PanelError as error:
            await self._fail(order, reason=error.code)
            raise ProvisioningFailed(error.code, retryable=error.retryable) from error

        subscription.renew(days=order.duration_days, now=now, extra_mib=order.traffic_mib)
        await self._subscriptions.update(subscription)

        order.mark_active(subscription_id=subscription.id, at=now)
        await self._orders.update(order)

        self._publish(order, subscription)
        return subscription

    # -- the retry queue ---------------------------------------------------

    async def drain_stuck(self, *, older_than_seconds: int = 60, limit: int = 50) -> Sequence[str]:
        """Retry every paid order still without a service.

        Returns the ids that were successfully provisioned. Failures are
        swallowed on purpose: one unreachable panel must not stop the sweep
        from fixing orders on the other four.
        """
        cutoff = self._clock.now() - timedelta(seconds=older_than_seconds)
        provisioned: list[str] = []
        for order in await self._orders.list_stuck(older_than=cutoff, limit=limit):
            try:
                await self.provision(order.id)
            except (ProvisioningFailed, NoCapacityAvailable, SubscriptionNotFound):
                continue
            provisioned.append(order.id)
        return tuple(provisioned)

    # -- helpers -----------------------------------------------------------

    async def _fail(self, order: Order, *, reason: str) -> None:
        if order.state is OrderState.PROVISIONING:
            order.fail(reason=reason)
            await self._orders.update(order)
            self._publish(order)

    def _publish(self, *aggregates: object) -> None:
        events: list[object] = []
        for aggregate in aggregates:
            events.extend(aggregate.collect_events())  # type: ignore[attr-defined]
        if events:
            self._events.publish_all(events)


def _quota_for(traffic_mib: int | None) -> TrafficQuota:
    """``None`` on the order means unlimited, and must not become zero bytes."""
    if traffic_mib is None:
        return TrafficQuota(None)
    return TrafficQuota(traffic_mib * BYTES_PER_MIB)


def panel_id_for(node_id: str) -> UUID:
    """The UUID an adapter for ``node_id`` is built with.

    Node ids are opaque strings in this schema while the panel contract wants a
    UUID, so a non-UUID id is folded into a stable namespace UUID rather than
    pretending it was one. Stability is the whole point: this id ends up inside
    every ``PanelAccountRef``, and a create and a later renew must derive the
    same one or the renew addresses an account that does not exist.

    Defined here, in the application layer, so the infrastructure provider that
    builds adapters and the service that rebuilds refs cannot drift apart.
    """
    try:
        return UUID(node_id)
    except ValueError:
        return uuid5(NAMESPACE_URL, f"geekvpn:node:{node_id}")


def _ref_for(subscription: Subscription, node: NodeRecord) -> PanelAccountRef:
    """Rebuild the panel pointer stored on the subscription."""
    return PanelAccountRef(
        panel_id=panel_id_for(node.id),
        username=subscription.remote_username or "",
        external_id=subscription.remote_id,
    )


__all__ = ["BYTES_PER_MIB", "ProvisioningService", "panel_id_for", "username_for"]
