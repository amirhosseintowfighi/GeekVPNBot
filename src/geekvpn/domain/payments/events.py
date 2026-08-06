"""Payment domain events.

Naming follows the project convention: ``<context>.<thing>.<past_tense>.v<N>``.
The version is in the name because these cross the outbox and become a public
contract the moment a consumer reads one.

Every event here carries **amounts as plain integers of Toman**, not ``Money``
objects. An event is a serialised message; embedding a value object in it
makes the wire format depend on a class definition that will drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from geekvpn.domain.base.events import DomainEvent


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceIssued(DomainEvent):
    name: ClassVar[str] = "billing.invoice.issued.v1"

    invoice_id: str
    number: str
    user_id: int
    total: int

    def payload(self) -> dict[str, Any]:
        return {
            "invoice_id": self.invoice_id,
            "number": self.number,
            "user_id": self.user_id,
            "total": self.total,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentInitiated(DomainEvent):
    name: ClassVar[str] = "billing.payment.initiated.v1"

    payment_id: str
    invoice_id: str
    user_id: int
    method: str
    amount: int

    def payload(self) -> dict[str, Any]:
        return {
            "payment_id": self.payment_id,
            "invoice_id": self.invoice_id,
            "user_id": self.user_id,
            "method": self.method,
            "amount": self.amount,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ProofSubmitted(DomainEvent):
    """A receipt photo or a transaction hash arrived.

    This is what puts a row in the admin review queue, so it carries the
    submission time: the queue is sorted by how long a customer has been
    waiting, and that clock starts here, not at invoice creation.
    """

    name: ClassVar[str] = "billing.payment.proof_submitted.v1"

    payment_id: str
    user_id: int
    method: str
    reference: str

    def payload(self) -> dict[str, Any]:
        return {
            "payment_id": self.payment_id,
            "user_id": self.user_id,
            "method": self.method,
            "reference": self.reference,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentApproved(DomainEvent):
    """Money is ours. The single trigger for provisioning.

    Nothing else in the system may start a subscription. Tying provisioning to
    this one event is what guarantees a service is never delivered against
    money we have not actually captured.
    """

    name: ClassVar[str] = "billing.payment.approved.v1"

    payment_id: str
    invoice_id: str
    user_id: int
    method: str
    amount: int
    approved_by: int | None
    """``None`` when approval was automatic (wallet or gateway)."""

    def payload(self) -> dict[str, Any]:
        return {
            "payment_id": self.payment_id,
            "invoice_id": self.invoice_id,
            "user_id": self.user_id,
            "method": self.method,
            "amount": self.amount,
            "approved_by": self.approved_by,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentRejected(DomainEvent):
    name: ClassVar[str] = "billing.payment.rejected.v1"

    payment_id: str
    user_id: int
    reason_fa: str
    rejected_by: int | None

    def payload(self) -> dict[str, Any]:
        return {
            "payment_id": self.payment_id,
            "user_id": self.user_id,
            "reason_fa": self.reason_fa,
            "rejected_by": self.rejected_by,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentFailed(DomainEvent):
    """A gateway attempt died. Distinct from a rejection by a human."""

    name: ClassVar[str] = "billing.payment.failed.v1"

    payment_id: str
    user_id: int
    reason: str

    def payload(self) -> dict[str, Any]:
        return {
            "payment_id": self.payment_id,
            "user_id": self.user_id,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentExpiredEvent(DomainEvent):
    """The proof window closed with nothing submitted."""

    name: ClassVar[str] = "billing.payment.expired.v1"

    payment_id: str
    user_id: int

    def payload(self) -> dict[str, Any]:
        return {"payment_id": self.payment_id, "user_id": self.user_id}


@dataclass(frozen=True, slots=True, kw_only=True)
class PaymentRefunded(DomainEvent):
    name: ClassVar[str] = "billing.payment.refunded.v1"

    payment_id: str
    user_id: int
    amount: int
    remaining: int
    """How much of the original payment is still refundable afterwards."""

    reason: str
    destination: str
    refunded_by: int | None

    def payload(self) -> dict[str, Any]:
        return {
            "payment_id": self.payment_id,
            "user_id": self.user_id,
            "amount": self.amount,
            "remaining": self.remaining,
            "reason": self.reason,
            "destination": self.destination,
            "refunded_by": self.refunded_by,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class WalletCredited(DomainEvent):
    name: ClassVar[str] = "billing.wallet.credited.v1"

    user_id: int
    amount: int
    balance_after: int
    kind: str
    reference: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "amount": self.amount,
            "balance_after": self.balance_after,
            "kind": self.kind,
            "reference": self.reference,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class WalletDebited(DomainEvent):
    name: ClassVar[str] = "billing.wallet.debited.v1"

    user_id: int
    amount: int
    balance_after: int
    kind: str
    reference: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "amount": self.amount,
            "balance_after": self.balance_after,
            "kind": self.kind,
            "reference": self.reference,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class DuplicateReceiptDetected(DomainEvent):
    """Someone submitted a receipt that was already used.

    Emitted even though the submission is rejected, because the *pattern*
    matters: one customer doing this three times is a fraud signal that no
    single rejection message conveys.
    """

    name: ClassVar[str] = "billing.payment.duplicate_receipt.v1"

    user_id: int
    reference: str
    existing_payment_id: str

    def payload(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "reference": self.reference,
            "existing_payment_id": self.existing_payment_id,
        }


__all__ = [
    "DuplicateReceiptDetected",
    "InvoiceIssued",
    "PaymentApproved",
    "PaymentExpiredEvent",
    "PaymentFailed",
    "PaymentInitiated",
    "PaymentRefunded",
    "PaymentRejected",
    "ProofSubmitted",
    "WalletCredited",
    "WalletDebited",
]
