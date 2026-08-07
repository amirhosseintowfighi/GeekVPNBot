"""Refunds.

Policy, stated once so it is not re-invented per caller:

**The wallet is the default destination, and it is a feature, not laziness.**
A wallet refund is instant, costs no bank fee, needs no card number from the
customer, and in practice the money is usually spent with us again. Returning
to the original card requires a manual bank transfer by a human and is offered
only when the customer asks for it.

A refund therefore does two things that must not come apart: it records the
refund against the payment, and - for wallet destinations - it credits the
wallet. Both happen here, in one call, or neither does.

The protection against a double refund is not a flag: it is the refundable
balance derived from the refund entries. Two operators refunding the same
order at once means the second finds nothing left to return.
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
from geekvpn.domain.payments.enums import (
    PaymentState,
    RefundDestination,
    RefundReason,
    TransactionKind,
)
from geekvpn.domain.payments.errors import RefundNotAllowed
from geekvpn.domain.payments.gateway import GatewayRegistry
from geekvpn.domain.payments.payment import Payment, RefundEntry


@dataclass(frozen=True, slots=True, kw_only=True)
class RefundRequest:
    payment_id: str
    actor_id: int
    reason: RefundReason
    note_fa: str
    amount: int | None = None
    """``None`` means a full refund of whatever is still refundable.

    Defaulting to the remaining balance rather than the original amount is
    what makes "refund the rest" safe after a partial refund.
    """

    destination: RefundDestination = RefundDestination.WALLET


@dataclass(frozen=True, slots=True, kw_only=True)
class RefundOutcome:
    entry: RefundEntry
    payment: Payment
    destination: RefundDestination
    wallet_credited: bool
    message_fa: str | None = None

    @property
    def fully_refunded(self) -> bool:
        return self.payment.state is PaymentState.REFUNDED


class RefundService:
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

    def refund(self, request: RefundRequest) -> RefundOutcome:
        payment = require_payment(self._payments, request.payment_id)
        now = self._clock.now()

        refundable = payment.refundable
        if refundable.amount <= 0:
            raise RefundNotAllowed(
                "There is nothing left to refund on this payment.",
                payment_id=payment.id,
                state=str(payment.state),
            )

        amount = Money(request.amount) if request.amount is not None else refundable
        destination = self._resolve_destination(payment, request)

        entry = payment.refund(
            amount,
            refund_id=self._ids.new_id(),
            reason=request.reason,
            destination=destination,
            note_fa=request.note_fa,
            at=now,
            actor_id=request.actor_id,
        )

        wallet = None
        if destination is RefundDestination.WALLET:
            wallet = self._wallets.get_or_create(payment.user_id)
            wallet.credit(
                amount,
                entry_id=self._ids.new_id(),
                kind=TransactionKind.REFUND,
                occurred_at=now,
                description_fa=("\u0628\u0627\u0632\u06af\u0634\u062a \u0648\u062c\u0647"),
                reference=payment.invoice_id,
                actor_id=request.actor_id,
            )
            self._wallets.save(wallet)

        if payment.state is PaymentState.REFUNDED:
            invoice = require_invoice(self._invoices, payment.invoice_id)
            invoice.mark_refunded()
            self._invoices.save(invoice)
            self._publish(invoice)

        self._payments.save(payment)
        self._audit.record(
            action="payment.refund",
            actor_id=request.actor_id,
            payment_id=payment.id,
            details={
                "amount": amount.amount,
                "destination": str(destination),
                "reason": str(request.reason),
                "remaining": payment.refundable.amount,
            },
        )
        self._publish(payment, wallet)

        return RefundOutcome(
            entry=entry,
            payment=payment,
            destination=destination,
            wallet_credited=wallet is not None,
        )

    def _resolve_destination(self, payment: Payment, request: RefundRequest) -> RefundDestination:
        """Honour a request for the original method only if it is possible.

        Asking a card-to-card adapter to refund online returns
        ``succeeded=False`` rather than raising, so the customer gets their
        money in the wallet instead of getting an error. Falling back beats
        failing.
        """
        if request.destination is not RefundDestination.ORIGINAL:
            return RefundDestination.WALLET
        if not payment.gateway_key or not self._gateways.has(payment.gateway_key):
            return RefundDestination.WALLET
        gateway = self._gateways.get(payment.gateway_key)
        if not gateway.capabilities.supports_online_refund:
            return RefundDestination.WALLET
        return RefundDestination.ORIGINAL

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


__all__ = ["RefundOutcome", "RefundRequest", "RefundService"]
