"""Mappers between the provisioning tables and the order/subscription aggregates.

One conversion lives here and nowhere else: the catalog keys (`plan_id`,
`product_id`, `campaign_id`) are ``uuid.UUID`` in the database and plain ``str``
in the domain. The domain deliberately does not know about UUIDs - it treats a
plan key as an opaque identifier - so the parsing happens at this boundary and
is never repeated in a service or a router.

Money is ``Money`` in the aggregates and a plain integer column in the table.
Same reasoning as the events: a column should not depend on a class definition.
"""

from __future__ import annotations

import uuid

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.provisioning.enums import (
    OrderSource,
    OrderState,
    SubscriptionState,
)
from geekvpn.domain.provisioning.order import Order
from geekvpn.domain.provisioning.subscription import Subscription
from geekvpn.infrastructure.persistence.models.provisioning import (
    OrderModel,
    SubscriptionModel,
)


def _uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value is None:
        return None
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _text(value: uuid.UUID | str | None) -> str | None:
    return None if value is None else str(value)


# -- order -----------------------------------------------------------------


def order_to_domain(model: OrderModel) -> Order:
    return Order.restore(
        model.id,
        number=model.number,
        user_id=model.user_id,
        plan_id=str(model.plan_id),
        product_id=_text(model.product_id),
        plan_name_fa=model.plan_name_fa,
        duration_days=model.duration_days,
        traffic_mib=model.traffic_mib,
        device_limit=model.device_limit,
        list_price=Money(model.list_price),
        discount=Money(model.discount),
        total=Money(model.total),
        state=OrderState(model.state),
        campaign_id=_text(model.campaign_id),
        coupon_code=model.coupon_code,
        invoice_id=model.invoice_id,
        is_renewal=model.is_renewal,
        renews_subscription_id=model.renews_subscription_id,
        placed_at=model.placed_at,
        paid_at=model.paid_at,
        provisioned_at=model.provisioned_at,
        failure_reason=model.failure_reason,
        source=OrderSource(model.source),
    )


def order_apply(model: OrderModel, order: Order) -> OrderModel:
    """Write the mutable half of an order.

    What is sold - plan, price, duration, traffic - is written once at insert
    and never touched again. An order is a record of an agreement; if the
    agreement changes, that is a new order, not an edit.
    """
    model.state = order.state.value
    model.invoice_id = order.invoice_id
    model.paid_at = order.paid_at
    model.provisioned_at = order.provisioned_at
    model.failure_reason = order.failure_reason
    return model


def order_to_row(order: Order) -> OrderModel:
    model = OrderModel(
        id=order.id,
        number=order.number,
        user_id=order.user_id,
        plan_id=_uuid(order.plan_id),
        product_id=_uuid(order.product_id),
        plan_name_fa=order.plan_name_fa,
        duration_days=order.duration_days,
        traffic_mib=order.traffic_mib,
        device_limit=order.device_limit,
        list_price=order.list_price.amount,
        discount=order.discount.amount,
        total=order.total.amount,
        campaign_id=_uuid(order.campaign_id),
        coupon_code=order.coupon_code,
        is_renewal=order.is_renewal,
        renews_subscription_id=order.renews_subscription_id,
        placed_at=order.placed_at,
        source=order.source.value,
    )
    return order_apply(model, order)


# -- subscription ----------------------------------------------------------


def subscription_to_domain(model: SubscriptionModel) -> Subscription:
    return Subscription.restore(
        model.id,
        user_id=model.user_id,
        order_id=model.order_id,
        plan_id=str(model.plan_id),
        state=SubscriptionState(model.state),
        node_id=model.node_id,
        remote_id=model.remote_id,
        reseller_id=None if model.reseller_id is None else str(model.reseller_id),
        # The column is nullable because a row can exist for a split second
        # before the panel answers; the aggregate wants a string.
        remote_username=model.remote_username or "",
        subscription_url=model.subscription_url,
        started_at=model.started_at,
        expires_at=model.expires_at,
        traffic_limit_mib=model.traffic_limit_mib,
        traffic_used_mib=model.traffic_used_mib,
        device_limit=model.device_limit,
        last_synced_at=model.last_synced_at,
        last_used_at=model.last_used_at,
        notified_expiry_days=model.notified_expiry_days or [],
        notified_traffic_percents=model.notified_traffic_percents or [],
        revoked_at=model.revoked_at,
        revoke_reason_fa=model.revoke_reason_fa,
        suspend_reason_fa=model.suspend_reason_fa,
    )


def subscription_apply(model: SubscriptionModel, subscription: Subscription) -> SubscriptionModel:
    model.state = subscription.state.value
    model.node_id = subscription.node_id
    model.reseller_id = (
        None if subscription.reseller_id is None else uuid.UUID(subscription.reseller_id)
    )
    model.remote_id = subscription.remote_id
    model.remote_username = subscription.remote_username
    model.subscription_url = subscription.subscription_url
    model.expires_at = subscription.expires_at
    model.traffic_limit_mib = subscription.traffic_limit_mib
    model.traffic_used_mib = subscription.traffic_used_mib
    model.device_limit = subscription.device_limit
    model.last_synced_at = subscription.last_synced_at
    model.last_used_at = subscription.last_used_at
    # Sorted so a diff of two rows is readable and a set's arbitrary order
    # never shows up as a spurious change in the audit trail.
    model.notified_expiry_days = sorted(subscription.notified_expiry_days)
    model.notified_traffic_percents = sorted(subscription.notified_traffic_percents)
    model.revoked_at = subscription.revoked_at
    model.revoke_reason_fa = subscription.revoke_reason_fa
    model.suspend_reason_fa = subscription.suspend_reason_fa
    return model


def subscription_to_row(subscription: Subscription) -> SubscriptionModel:
    model = SubscriptionModel(
        id=subscription.id,
        user_id=subscription.user_id,
        order_id=subscription.order_id,
        plan_id=_uuid(subscription.plan_id),
        started_at=subscription.started_at,
        expires_at=subscription.expires_at,
    )
    return subscription_apply(model, subscription)


__all__ = [
    "order_apply",
    "order_to_domain",
    "order_to_row",
    "subscription_apply",
    "subscription_to_domain",
    "subscription_to_row",
]
