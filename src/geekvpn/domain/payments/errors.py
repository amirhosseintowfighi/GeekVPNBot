"""Payment error taxonomy.

Every error here is *expected*: a customer submitted a duplicate receipt, an
admin tried to approve an order twice, a wallet ran out of money. None of them
are bugs, so all of them subclass ``DomainError`` and are caught and rendered
in Persian by the bot and the admin panel.

The one rule that shapes this file: **a payment error must say what the money
is doing now**, not merely that something failed. "Payment failed" forces a
support ticket; "this receipt was already used for order #1204" closes one.
"""

from __future__ import annotations

from geekvpn.domain.base.errors import (
    ConflictError,
    DomainError,
    NotFoundError,
    ValidationError,
)


class PaymentError(DomainError):
    code = "payment_error"
    message = "A payment error occurred."


class PaymentNotFound(NotFoundError):
    code = "payment_not_found"
    message = "The payment was not found."


class InvoiceNotFound(NotFoundError):
    code = "invoice_not_found"
    message = "The invoice was not found."


class PaymentValidationError(ValidationError):
    code = "payment_validation_error"
    message = "The payment data is invalid."


class IllegalPaymentTransition(ConflictError):
    """Raised when a state change is not permitted from the current state.

    This is the guard that makes double-approval impossible. Two admins
    clicking \"approve\" on the same order in the same second both reach the
    aggregate; the second one finds the payment already APPROVED and is
    rejected here rather than provisioning a second subscription.
    """

    code = "illegal_payment_transition"
    message = "This payment cannot move to that state."

    def __init__(self, *, current: str, target: str) -> None:
        super().__init__(
            f"A payment in state {current!r} cannot move to {target!r}.",
            current=current,
            target=target,
        )


class InsufficientFunds(PaymentError):
    """The wallet balance cannot cover the amount.

    Carries the shortfall so the bot can offer a top-up button pre-filled with
    exactly what is missing, instead of sending the customer to a blank form.
    """

    code = "insufficient_funds"
    message = "Wallet balance is not enough."

    def __init__(self, *, balance: int, required: int) -> None:
        super().__init__(
            "Wallet balance is not enough for this purchase.",
            balance=balance,
            required=required,
            shortfall=max(0, required - balance),
        )


class DuplicateReceipt(ConflictError):
    """The same receipt file or transaction hash was submitted twice.

    The commonest fraud attempt in card-to-card sales is forwarding one
    genuine receipt against several orders. Detection lives in the domain, not
    in the admin's memory.
    """

    code = "duplicate_receipt"
    message = "This receipt has already been submitted."

    def __init__(self, *, reference: str, existing_payment: str) -> None:
        super().__init__(
            "This receipt has already been submitted for another payment.",
            reference=reference,
            existing_payment=existing_payment,
        )


class RefundNotAllowed(ConflictError):
    code = "refund_not_allowed"
    message = "This payment cannot be refunded."


class RefundExceedsPayment(PaymentValidationError):
    """Partial refunds may not sum to more than what was captured."""

    code = "refund_exceeds_payment"
    message = "The refund is larger than the remaining refundable amount."

    def __init__(self, *, requested: int, refundable: int) -> None:
        super().__init__(
            "The refund is larger than the remaining refundable amount.",
            requested=requested,
            refundable=refundable,
        )


class GatewayError(PaymentError):
    """An external provider misbehaved.

    Deliberately distinct from a *declined* payment. A decline is a business
    outcome the customer must act on; a gateway error is our problem and must
    never be shown to the customer as \"your payment failed\".
    """

    code = "gateway_error"
    message = "The payment provider is not responding correctly."

    def __init__(self, message: str | None = None, *, gateway: str, retryable: bool = True) -> None:
        super().__init__(message, gateway=gateway, retryable=retryable)
        self.retryable = retryable


class GatewayNotRegistered(NotFoundError):
    code = "gateway_not_registered"
    message = "No payment gateway is registered under that key."


class VerificationFailed(PaymentError):
    """Automatic verification ran and did not confirm the payment.

    Not the same as an error: verification worked, the answer was \"no\".
    """

    code = "verification_failed"
    message = "The payment could not be verified."

    def __init__(self, message: str | None = None, *, reason: str) -> None:
        super().__init__(message, reason=reason)
        self.reason = reason


class AmountMismatch(VerificationFailed):
    """The provider confirmed a payment for a different amount.

    Underpayment must never provision. Overpayment must never be silently
    pocketed: the application layer credits the surplus to the wallet.
    """

    code = "amount_mismatch"

    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(
            "The paid amount does not match the invoice.",
            reason="amount_mismatch",
        )
        self.details.update(expected=expected, actual=actual)
        self.expected = expected
        self.actual = actual


class PaymentExpired(ConflictError):
    """The window for paying this invoice has closed.

    Matters most for crypto, where a quoted rate cannot be honoured forever.
    """

    code = "payment_expired"
    message = "The payment window for this invoice has expired."


__all__ = [
    "AmountMismatch",
    "DuplicateReceipt",
    "GatewayError",
    "GatewayNotRegistered",
    "IllegalPaymentTransition",
    "InsufficientFunds",
    "PaymentError",
    "PaymentExpired",
    "PaymentNotFound",
    "PaymentValidationError",
    "RefundExceedsPayment",
    "RefundNotAllowed",
    "VerificationFailed",
]
