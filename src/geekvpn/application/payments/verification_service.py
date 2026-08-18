"""Automatic payment verification.

Today every registered gateway answers ``INCONCLUSIVE``, because a human reads
the receipts. This service still exists, and running it now rather than later
is the point: when a real gateway is registered, verification is already
wired, already scheduled, and already tested.

The three outcomes that are not "confirmed" each need different handling, and
collapsing them is the classic way to lose money:

* ``INCONCLUSIVE`` - not an answer. Leave the payment alone and ask again
  later. A crypto transfer with one confirmation lives here.
* ``MISMATCH``     - the provider confirms a different amount. A human
  decides, because the right response depends on the direction and size.
* ``DECLINED``     - a real no. Fail the payment so the customer can retry.

Overpayment is settled automatically, underpayment never is. Someone who
sends more than asked should not wait for an operator; someone who sends less
must not be provisioned.
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
from geekvpn.application.payments.topups import credit_topup
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import (
    PaymentState,
    TransactionKind,
    VerificationOutcome,
)
from geekvpn.domain.payments.gateway import GatewayRegistry, VerificationResult
from geekvpn.domain.payments.payment import Payment


@dataclass(frozen=True, slots=True, kw_only=True)
class VerificationReport:
    """What the sweeper did, so a scheduler can log something meaningful."""

    checked: int = 0
    confirmed: int = 0
    declined: int = 0
    retry_later: int = 0
    escalated: int = 0


class VerificationService:
    """Asks providers whether money arrived, and acts on the answer."""

    __slots__ = (
        "_audit",
        "_clock",
        "_events",
        "_gateways",
        "_ids",
        "_invoices",
        "_payments",
        "_wallets",
    )

    def __init__(
        self,
        *,
        payments: PaymentRepository,
        invoices: InvoiceRepository,
        wallets: WalletRepository,
        gateways: GatewayRegistry,
        clock: Clock,
        ids: IdGenerator,
        events: EventPublisher,
        audit: PaymentAuditLog,
    ) -> None:
        self._payments = payments
        self._invoices = invoices
        self._wallets = wallets
        self._gateways = gateways
        self._clock = clock
        self._ids = ids
        self._events = events
        self._audit = audit

    def verify(self, payment_id: str) -> VerificationResult:
        """Verify one payment.

        Idempotent by construction: a payment that has already settled is
        reported as confirmed without calling the provider again. Callbacks
        fire more than once, and the second one must be harmless.
        """
        payment = require_payment(self._payments, payment_id)

        if payment.state.is_settled():
            return VerificationResult(
                outcome=VerificationOutcome.CONFIRMED, amount=payment.captured
            )
        if payment.state.is_terminal():
            return VerificationResult(outcome=VerificationOutcome.DECLINED)

        invoice = require_invoice(self._invoices, payment.invoice_id)
        gateway = self._gateways.get(payment.gateway_key or payment.method.value)

        reference = payment.gateway_reference or (payment.proof.reference if payment.proof else "")
        result = gateway.verify(payment_id=payment.id, reference=reference, expected=invoice.total)

        if result.outcome is VerificationOutcome.CONFIRMED:
            self._settle(payment=payment, invoice_total=invoice.total, result=result)
        elif result.outcome is VerificationOutcome.DECLINED:
            payment.fail(reason=result.message_fa or "declined by provider")
            self._payments.save(payment)
            self._publish(payment)
        elif result.outcome is VerificationOutcome.MISMATCH:
            self._escalate(payment)
        # INCONCLUSIVE deliberately does nothing: no state change, no event.

        self._audit.record(
            action="payment.verify",
            actor_id=None,
            payment_id=payment.id,
            details={"outcome": str(result.outcome)},
        )
        return result

    def sweep(self, *, limit: int = 100) -> VerificationReport:
        """Re-check everything sitting at a gateway."""
        checked = confirmed = declined = retry = escalated = 0
        for payment in self._payments.in_state(PaymentState.PENDING_GATEWAY, limit=limit):
            checked += 1
            result = self.verify(payment.id)
            if result.outcome is VerificationOutcome.CONFIRMED:
                confirmed += 1
            elif result.outcome is VerificationOutcome.DECLINED:
                declined += 1
            elif result.outcome is VerificationOutcome.MISMATCH:
                escalated += 1
            else:
                retry += 1
        return VerificationReport(
            checked=checked,
            confirmed=confirmed,
            declined=declined,
            retry_later=retry,
            escalated=escalated,
        )

    # -- internals ---------------------------------------------------------

    def _settle(
        self, *, payment: Payment, invoice_total: Money, result: VerificationResult
    ) -> None:
        actual = result.amount or invoice_total

        if actual.amount < invoice_total.amount:
            # A confirmed *underpayment* is still not a sale. It goes to a
            # human rather than being silently failed, because the customer
            # really did send money and someone must decide what happens to it.
            self._escalate(payment)
            return

        now = self._clock.now()
        invoice = require_invoice(self._invoices, payment.invoice_id)
        payment.approve(at=now, approved_by=None, captured=actual)
        invoice.mark_paid(payment_id=payment.id, at=now)

        # Same rule as the reviewer path: a top-up's principal is credited on
        # settlement, whichever route settled it.
        wallet = credit_topup(
            invoice,
            wallets=self._wallets,
            amount=invoice_total,
            entry_id=self._ids.new_id(),
            now=now,
        )

        surplus = Money(actual.amount - invoice_total.amount)
        if surplus.amount > 0:
            # Reuse the aggregate credit_topup already loaded. Re-reading
            # here would discard the top-up entry it just added, so an
            # overpaid top-up would credit the surplus and lose the
            # principal.
            wallet = wallet or self._wallets.get_or_create(payment.user_id)
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
        self._publish(payment, invoice, wallet)

    def _escalate(self, payment: Payment) -> None:
        """Put a machine-ambiguous payment in front of a person."""
        if payment.state is PaymentState.PENDING_GATEWAY:
            payment.flag_for_review()
            self._payments.save(payment)
            self._publish(payment)

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


__all__ = ["VerificationReport", "VerificationService"]
