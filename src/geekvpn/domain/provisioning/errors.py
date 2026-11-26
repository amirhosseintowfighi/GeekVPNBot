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


class ServiceNameTooLong(OrderValidationError):
    """A customer's name for their service does not fit on a button."""

    code = "service_name_too_long"
    message = "این اسم طولانیه. حداکثر ۳۲ حرف."


class TransferToSelf(OrderValidationError):
    """The recipient of a transfer is the service's own owner."""

    code = "transfer_to_self"
    message = "این سرویس همین الان مال خودته 🙂"


class RefundNotAllowed(ConflictError):
    """A refund for an unused service was refused; the message says why.

    Each reason has its own subclass so a client can branch on ``code``
    without parsing the sentence. The bot only ever reads ``message``.
    """

    code = "unused_refund_refused"
    message = "برگشت وجه برای این سرویس ممکن نیست."


class RefundDisabled(RefundNotAllowed):
    code = "refund_disabled"
    message = "برگشت وجه در این فروشگاه فعال نیست."


class RefundServiceNotActive(RefundNotAllowed):
    code = "refund_service_not_active"
    message = "فقط سرویس فعال قابل برگشت وجهه."


class RefundWindowClosed(RefundNotAllowed):
    code = "refund_window_closed"


class RefundNotPurchased(RefundNotAllowed):
    code = "refund_not_purchased"
    message = "این سرویس خریداری نشده که وجهش برگرده."


class RefundServiceUsed(RefundNotAllowed):
    code = "refund_service_used"
    message = "این سرویس استفاده شده و وجهش برنمی‌گرده."


class DailyPurchaseLimitReached(ConflictError):
    """This customer has bought as many services today as the shop allows."""

    code = "daily_purchase_limit"
    message = "سقف خرید امروزت پر شده. فردا دوباره می‌تونی خرید کنی."


class RotationUnavailable(ConflictError):
    """This service's panel cannot issue a new link, or it has no panel at all."""

    code = "rotation_unavailable"
    message = "A new link cannot be issued for this service."


class FreeTrialAlreadyClaimed(ConflictError):
    """One free trial per customer, and this one has had it."""

    code = "free_trial_already_claimed"
    message = "This customer has already had the free trial."


class FreeTrialUnavailable(ConflictError):
    """Nothing on sale that a trial could be cut from.

    The trial borrows a real plan for its product and tier, so a shop with no
    published tunnel or direct plan has nothing to give.
    """

    code = "free_trial_unavailable"
    message = "No plan is available for a free trial."


__all__ = [
    "DailyPurchaseLimitReached",
    "FreeTrialAlreadyClaimed",
    "FreeTrialUnavailable",
    "IllegalOrderTransition",
    "IllegalSubscriptionTransition",
    "NoCapacityAvailable",
    "NodeNotFound",
    "OrderNotFound",
    "OrderValidationError",
    "ProvisioningError",
    "ProvisioningFailed",
    "RefundDisabled",
    "RefundNotAllowed",
    "RefundNotPurchased",
    "RefundServiceNotActive",
    "RefundServiceUsed",
    "RefundWindowClosed",
    "RotationUnavailable",
    "ServiceNameTooLong",
    "SubscriptionNotFound",
    "SubscriptionRevoked",
    "TransferToSelf",
]


class DeliveryPending(ProvisioningError):
    """Paid for, not yet delivered, and the money must stay accounted for.

    Wallet checkout settles the payment and provisions in the same breath. When
    the panel refuses at that last step the customer has already been debited,
    so the failure is not "something went wrong" - it is a service that is owed
    and is coming. The order survives in FAILED for the retry queue, which is
    what the admin panel's retry button acts on.

    Carries its own Persian message because the customer reads it directly.
    """

    code = "delivery_pending"
    message = "پرداخت انجام شد و سرویس به‌زودی فعال می‌شه."
