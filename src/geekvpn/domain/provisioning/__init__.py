"""Provisioning: orders, subscriptions, and the servers they live on.

This is the context that turns money into a working account. It depends on
catalog (for ``Money``) and on nothing else in the domain - in particular it
never imports payments, because an order must be describable without knowing
how it was paid for.
"""

from geekvpn.domain.provisioning.enums import (
    NodeState,
    OrderSource,
    OrderState,
    SubscriptionState,
)
from geekvpn.domain.provisioning.errors import (
    IllegalOrderTransition,
    IllegalSubscriptionTransition,
    NoCapacityAvailable,
    NodeNotFound,
    OrderNotFound,
    OrderValidationError,
    ProvisioningError,
    ProvisioningFailed,
    SubscriptionNotFound,
    SubscriptionRevoked,
)
from geekvpn.domain.provisioning.events import (
    OrderCancelled,
    OrderFailed,
    OrderPaid,
    OrderPlaced,
    OrderProvisioned,
    SubscriptionActivated,
    SubscriptionExhausted,
    SubscriptionExpired,
    SubscriptionRenewed,
    SubscriptionRevokedEvent,
    SubscriptionSuspended,
)
from geekvpn.domain.provisioning.order import Order
from geekvpn.domain.provisioning.subscription import (
    EXPIRY_REMINDER_DAYS,
    MIB_PER_GIB,
    TRAFFIC_REMINDER_PERCENTS,
    Subscription,
)

__all__ = [
    "EXPIRY_REMINDER_DAYS",
    "MIB_PER_GIB",
    "TRAFFIC_REMINDER_PERCENTS",
    "IllegalOrderTransition",
    "IllegalSubscriptionTransition",
    "NoCapacityAvailable",
    "NodeNotFound",
    "NodeState",
    "Order",
    "OrderCancelled",
    "OrderFailed",
    "OrderNotFound",
    "OrderPaid",
    "OrderPlaced",
    "OrderProvisioned",
    "OrderSource",
    "OrderState",
    "OrderValidationError",
    "ProvisioningError",
    "ProvisioningFailed",
    "Subscription",
    "SubscriptionActivated",
    "SubscriptionExhausted",
    "SubscriptionExpired",
    "SubscriptionNotFound",
    "SubscriptionRenewed",
    "SubscriptionRevoked",
    "SubscriptionRevokedEvent",
    "SubscriptionState",
    "SubscriptionSuspended",
]
