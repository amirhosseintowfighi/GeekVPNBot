"""Provisioning error taxonomy.

Same rule as billing: an error must say what the customer's *service* is doing
now. "Provisioning failed" starts a support ticket; "your payment is safe and
we are retrying on another server" prevents one.
"""

from __future__ import annotations

from geekvpn.domain.base.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)


class ProvisioningError(DomainError):
    code = "provisioning_error"
    message = "A provisioning error occurred."


class OrderNotFound(NotFoundError):
    code = "order_not_found"
    message = "The order was not found."


class SubscriptionNotFound(NotFoundError):
    code = "subscription_not_found"
    message = "The subscription was not found."


class NodeNotFound(NotFoundError):
    code = "node_not_found"
    message = "The node was not found."


class OrderValidationError(ValidationError):
    code = "order_validation_error"
    message = "The order data is invalid."


class IllegalOrderTransition(ConflictError):
    code = "illegal_order_transition"

    def __init__(self, *, current: str, target: str) -> None:
        super().__init__(
            f"An order cannot move from {current} to {target}.",
            current=current,
            target=target,
        )


class IllegalSubscriptionTransition(ConflictError):
    code = "illegal_subscription_transition"

    def __init__(self, *, current: str, target: str) -> None:
        super().__init__(
            f"A subscription cannot move from {current} to {target}.",
            current=current,
            target=target,
        )


class SubscriptionRevoked(ConflictError):
    code = "subscription_revoked"
    message = "This subscription was revoked and cannot be changed."


class NoCapacityAvailable(ProvisioningError):
    """Every node is full, offline, or closed to new accounts.

    Raised *before* taking money wherever possible. Selling a subscription we
    cannot deliver is the single worst failure mode this system has.
    """

    code = "no_capacity_available"
    message = "No server currently has room for a new account."


class ProvisioningFailed(ProvisioningError):
    code = "provisioning_failed"

    def __init__(self, reason: str, *, retryable: bool = True) -> None:
        super().__init__(f"Provisioning failed: {reason}", reason=reason, retryable=retryable)


__all__ = [
    "IllegalOrderTransition",
    "IllegalSubscriptionTransition",
    "NoCapacityAvailable",
    "NodeNotFound",
    "OrderNotFound",
    "OrderValidationError",
    "ProvisioningError",
    "ProvisioningFailed",
    "SubscriptionNotFound",
    "SubscriptionRevoked",
]
