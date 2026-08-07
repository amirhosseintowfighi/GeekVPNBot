"""Manual review: a human deciding whether money arrived.

This is the service behind the admin panel's order queue. It is short on
purpose - the state machine lives in the aggregate - but it owns three things
the aggregate cannot:

1. **Marking the invoice paid** alongside approving the payment. Those are two
   aggregates and must move together.
2. **Crediting overpayment to the wallet.** A customer who transfers 700,000
   against a 680,000 invoice must not lose 20,000, and must not be blocked
   either. The surplus becomes wallet credit.
3. **Refusing to approve on underpayment.** Under-transfer never provisions.
   It goes back to the customer with the shortfall spelled out.
"""

from __future__ import annotations

from dataclasses import dataclass

from geekvpn.application.payments.loaders import require_invoice, require_payment
from geekvpn.application.payments.ports import (
    Clock,
    EventPublisher,
    IdGenerator,
    InvoiceRepository,
    PaymentAuditLog,
    PaymentRepository,
    WalletRepository,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import PaymentState, TransactionKind
from geekvpn.domain.payments.errors import (
    AmountMismatch,
)
from geekvpn.domain.payments.payment import Payment


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalRequest:
    payment_id: str
    actor_id: int
    actual_amount: int | None = None
    """What the reviewer read off the receipt.

    ``None`` means "it matches the invoice", which is the overwhelmingly
    common case and must not require typing a number.
    """


class PaymentReviewService:
    """Approve, reject, or ask again for a manually-paid order."""

    __slots__ = ("_audit", "_clock", "_events", "_ids", "_invoices", "_payments", "_wallets")

    def __init__(
        self,
        *,
        payments: PaymentRepository,
        invoices: InvoiceRepository,
        wallets: WalletRepository,
        clock: Clock,
        ids: IdGenerator,
        events: EventPublisher,
        audit: PaymentAuditLog,
    ) -> None:
        self._payments = payments
        self._invoices = invoices
        self._wallets = wallets
        self._clock = clock
        self._ids = ids
        self._events = events
        self._audit = audit

    def approve(self, request: ApprovalRequest) -> Payment:
        """Confirm the money arrived and let provisioning start.

        Concurrency: two operators clicking approve in the same second both
        reach this method. The first moves the aggregate to APPROVED; the
        second gets ``IllegalPaymentTransition`` from the state machine rather
        than provisioning a second subscription.
        """
        payment = require_payment(self._payments, request.payment_id)
        invoice = require_invoice(self._invoices, payment.invoice_id)
        now = self._clock.now()

        expected = invoice.total
        actual = Money(request.actual_amount) if request.actual_amount is not None else expected

        if actual.amount < expected.amount:
            # Never provision on an underpayment. The reviewer is told the
            # shortfall so they can tell the customer exactly what to send.
            raise AmountMismatch(expected=expected.amount, actual=actual.amount)

        surplus = Money(actual.amount - expected.amount)

        payment.approve(at=now, approved_by=request.actor_id, captured=actual)
        invoice.mark_paid(payment_id=payment.id, at=now)

        wallet = None
        if surplus.amount > 0:
            # Overpayment is the customer's money. It is credited, not kept.
            wallet = self._wallets.get_or_create(payment.user_id)
            wallet.credit(
                surplus,
                entry_id=self._ids.new_id(),
                kind=TransactionKind.OVERPAYMENT,
                occurred_at=now,
                description_fa=(
                    "\u0645\u0627\u0628\u0647\u200c\u0627\u0644\u062a\u0641\u0627\u0648\u062a "
                    "\u067e\u0631\u062f\u0627\u062e\u062a \u0627\u0636\u0627\u0641\u06cc"
                ),
                reference=invoice.number,
            )
            self._wallets.save(wallet)

        self._payments.save(payment)
        self._invoices.save(invoice)
        self._audit.record(
            action="payment.approve",
            actor_id=request.actor_id,
            payment_id=payment.id,
            details={
                "invoice": invoice.number,
                "captured": actual.amount,
                "surplus": surplus.amount,
            },
        )
        self._publish(payment, invoice, wallet)
        return payment

    def reject(self, *, payment_id: str, actor_id: int, reason_fa: str) -> Payment:
        """Decline. The reason is shown to the customer word for word."""
        payment = require_payment(self._payments, payment_id)
        payment.reject(at=self._clock.now(), reason_fa=reason_fa, rejected_by=actor_id)
        self._payments.save(payment)
        self._audit.record(
            action="payment.reject",
            actor_id=actor_id,
            payment_id=payment.id,
            details={"reason_fa": reason_fa},
        )
        self._publish(payment)
        return payment

    def request_better_proof(self, *, payment_id: str, actor_id: int) -> Payment:
        """Send an unreadable receipt back without declining the sale.

        A blurred photo from an honest customer is not fraud. Rejecting it
        loses the order; asking again does not.
        """
        payment = require_payment(self._payments, payment_id)
        payment.request_better_proof()
        self._payments.save(payment)
        self._audit.record(
            action="payment.request_proof",
            actor_id=actor_id,
            payment_id=payment.id,
        )
        self._publish(payment)
        return payment

    def expire_stale(self) -> int:
        """Close payment windows that have run out. Driven by a scheduler.

        Only touches payments that are still waiting on the customer. A
        payment sitting in PENDING_REVIEW is waiting on *us* and must never be
        expired out from under a customer who did their part.
        """
        now = self._clock.now()
        closed = 0
        for payment in self._payments.expiring_before(now):
            if payment.state is not PaymentState.AWAITING_PROOF:
                continue
            payment.expire()
            self._payments.save(payment)
            self._publish(payment)
            closed += 1
        return closed

    def _publish(self, *aggregates: object) -> None:
        collected: list[object] = []
        for aggregate in aggregates:
            if aggregate is None:
                continue
            collect = getattr(aggregate, "collect_events", None)
            if collect is not None:
                collected.extend(collect())
        if collected:
            self._events.publish_all(collected)


__all__ = ["ApprovalRequest", "PaymentReviewService"]
