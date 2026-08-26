"""Checkout: turning an intention to buy into money.

This service owns the four things that must not be duplicated anywhere else:

1. **Issuing the invoice** - one number per purchase, reserved atomically.
2. **Choosing the gateway** - by key, from the registry, never by ``if``.
3. **Duplicate receipt detection** - the one check an aggregate cannot make,
   because it needs a view across payments.
4. **Settling wallet payments immediately** - the only method that captures
   money inside the same transaction that created the payment.

Everything else (approving, rejecting, refunding, verifying) lives in sibling
services, because those are operated by different actors at different times.

A note on the free-invoice case: a 100% coupon produces a zero total. The
system must still issue an invoice and still emit ``PaymentApproved``, because
provisioning listens to that event and nothing else. A free order that skips
the payment system is a free order that never provisions.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from geekvpn.application.payments.loaders import require_payment
from geekvpn.application.payments.ports import (
    Clock,
    EventPublisher,
    IdGenerator,
    InvoiceRepository,
    PaymentAuditLog,
    PaymentRepository,
    ReceiptDigestRepository,
    WalletRepository,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import (
    PaymentMethod,
    PaymentState,
    TransactionKind,
)
from geekvpn.domain.payments.errors import (
    DuplicateReceipt,
    PaymentExpired,
    PaymentNotFound,
    PaymentValidationError,
)
from geekvpn.domain.payments.events import DuplicateReceiptDetected
from geekvpn.domain.payments.gateway import CheckoutInstruction, GatewayRegistry
from geekvpn.domain.payments.invoice import (
    Invoice,
    InvoiceLine,
    format_invoice_number,
)
from geekvpn.domain.payments.payment import Payment
from geekvpn.domain.payments.proof import PaymentProof
from geekvpn.domain.payments.wallet import MIN_TOPUP

#: How far the identifying remainder reaches. Under a thousand Toman, so it is
#: a rounding error to the customer and still leaves a reviewer a thousand
#: distinguishable amounts at any one price.
IDENTIFIER_CEILING: Final = 999

IDENTIFIER_LINE_FA: Final = "شناسه پرداخت (برای تطبیق فیش)"


def _identifying_line() -> InvoiceLine:
    """A few Toman that make one transfer tell itself apart from another.

    A manually reviewed method is matched by a human reading an amount off a
    receipt. Two customers buying the same plan in the same hour transfer the
    same number, and the reviewer then holds two identical receipts with no way
    to say which invoice each belongs to - so one of them waits, or the wrong
    one is approved.

    It is an invoice *line* rather than a nudge to the price: the invoice total
    must stay the sum of its lines, and the customer is owed a view of the
    figure they were quoted next to the figure they must transfer.

    `secrets` rather than `random`, because the remainder is the thing that
    tells two payments apart, and a predictable one lets somebody aim a receipt
    at another customer's invoice.
    """
    # Never zero: a zero remainder is the collision this exists to avoid.
    return InvoiceLine(
        title_fa=IDENTIFIER_LINE_FA,
        # Added, never subtracted - subtracting could drop a small invoice
        # under a gateway's minimum.
        amount=secrets.randbelow(IDENTIFIER_CEILING) + 1,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckoutRequest:
    """Everything needed to start taking money.

    ``lines`` rather than a single price, so the invoice records the plan and
    each discount separately. The customer must be able to see what they were
    charged and what they were given.
    """

    user_id: int
    subject_fa: str
    lines: Sequence[InvoiceLine]
    gateway_key: str
    jalali_year: int
    metadata: dict[str, str] | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CheckoutResult:
    invoice: Invoice
    payment: Payment
    instruction: CheckoutInstruction

    @property
    def settled(self) -> bool:
        return self.payment.state is PaymentState.APPROVED


class CheckoutService:
    """Starts payments and accepts proof for them."""

    __slots__ = (
        "_audit",
        "_clock",
        "_digests",
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
        invoices: InvoiceRepository,
        payments: PaymentRepository,
        wallets: WalletRepository,
        gateways: GatewayRegistry,
        clock: Clock,
        ids: IdGenerator,
        events: EventPublisher,
        audit: PaymentAuditLog,
        digests: ReceiptDigestRepository | None = None,
    ) -> None:
        self._invoices = invoices
        self._payments = payments
        self._wallets = wallets
        self._gateways = gateways
        self._clock = clock
        self._ids = ids
        self._events = events
        self._audit = audit
        self._digests = digests

    # -- starting ----------------------------------------------------------

    def begin(self, request: CheckoutRequest) -> CheckoutResult:
        """Issue an invoice and start a payment against it."""
        now = self._clock.now()
        gateway = self._gateways.get(request.gateway_key)

        lines = tuple(request.lines)
        # Not on a free invoice: a 100% coupon must stay free, and asking for
        # 500 Toman to prove it would be worse than any collision.
        if gateway.capabilities.requires_manual_review and sum(
            line.amount for line in lines
        ) > 0:
            lines = (*lines, _identifying_line())

        sequence = self._invoices.next_sequence(year=request.jalali_year)
        invoice = Invoice.issue(
            self._ids.new_id(),
            number=format_invoice_number(year=request.jalali_year, sequence=sequence),
            user_id=request.user_id,
            subject_fa=request.subject_fa,
            lines=lines,
            issued_at=now,
            metadata=dict(request.metadata or {}),
        )

        total = invoice.total
        if not gateway.capabilities.accepts(total) and not invoice.is_free:
            raise PaymentValidationError(
                "This payment method does not accept that amount.",
                gateway=gateway.key,
                amount=total.amount,
            )

        payment = Payment.start(
            self._ids.new_id(),
            invoice_id=invoice.id,
            user_id=request.user_id,
            method=gateway.method,
            # A free invoice still needs a positive payment to exist, because
            # Money forbids a zero payment. One Toman is not charged to
            # anyone: the wallet branch below settles it without a debit.
            amount=total if total.amount > 0 else Money(1),
            created_at=now,
            gateway_key=gateway.key if gateway.method is PaymentMethod.GATEWAY else None,
        )

        instruction = gateway.begin(
            payment_id=payment.id,
            amount=total,
            user_id=request.user_id,
            invoice_number=invoice.number,
        )
        # Kept on the payment, not re-derived when the screen is reopened.
        #
        # A deployment can have several destination cards and the registry hands
        # out one of them at random, to spread transfers across accounts. That
        # made the card the customer saw depend on when they looked: the bot
        # showed one, and the Mini App payment screen an hour later showed
        # another, for the same transfer.
        payment.metadata.update(instruction.metadata)

        if invoice.is_free:
            self._settle_free(invoice=invoice, payment=payment)
        elif gateway.method is PaymentMethod.WALLET:
            self._settle_from_wallet(invoice=invoice, payment=payment, amount=total)
        elif gateway.method.needs_proof():
            window = self._proof_window(gateway.method)
            payment.await_proof(expires_at=now + window)
            instruction = CheckoutInstruction(
                payment_id=instruction.payment_id,
                method=instruction.method,
                amount=instruction.amount,
                expires_at=payment.expires_at,
                redirect_url=instruction.redirect_url,
                address=instruction.address,
                network=instruction.network,
                instructions_fa=instruction.instructions_fa,
                metadata=dict(instruction.metadata),
            )
        else:
            payment.send_to_gateway(gateway_key=gateway.key, reference=instruction.payment_id)

        self._invoices.save(invoice)
        self._payments.save(payment)
        self._publish(invoice, payment)
        self._audit.record(
            action="payment.begin",
            actor_id=None,
            payment_id=payment.id,
            details={
                "invoice": invoice.number,
                "gateway": gateway.key,
                "amount": total.amount,
            },
        )
        return CheckoutResult(invoice=invoice, payment=payment, instruction=instruction)

    def begin_topup(
        self, *, user_id: int, amount: Money, gateway_key: str, jalali_year: int
    ) -> CheckoutResult:
        """Top up a wallet.

        Modelled as an ordinary invoice so that a top-up appears in invoice
        history like everything else. Paying for a top-up *from* the wallet is
        refused here rather than producing a zero-sum ledger pair.
        """
        if gateway_key == "wallet":
            raise PaymentValidationError("A wallet cannot be topped up from itself.")
        if amount.amount < MIN_TOPUP:
            raise PaymentValidationError(
                "The top-up amount is below the minimum.",
                amount=amount.amount,
                minimum=MIN_TOPUP,
            )
        return self.begin(
            CheckoutRequest(
                user_id=user_id,
                subject_fa="\u0634\u0627\u0631\u0698 \u06a9\u06cc\u0641 \u067e\u0648\u0644",
                lines=[
                    InvoiceLine(
                        title_fa="\u0634\u0627\u0631\u0698 \u06a9\u06cc\u0641 \u067e\u0648\u0644",
                        amount=amount.amount,
                    )
                ],
                gateway_key=gateway_key,
                jalali_year=jalali_year,
                metadata={"kind": "topup"},
            )
        )

    # -- proof -------------------------------------------------------------

    def submit_proof(
        self, *, payment_id: str, proof: PaymentProof, user_id: int | None = None
    ) -> Payment:
        """Accept a receipt image or a transaction hash.

        Order of checks matters and is deliberate:

        1. expiry, because accepting proof for a dead payment then expiring it
           would be a worse experience than an honest "too late";
        2. duplicate, because a reused receipt must never enter the review
           queue and waste an operator's attention.
        """
        payment = require_payment(self._payments, payment_id)
        if user_id is not None and payment.user_id != user_id:
            # Answered as "no such payment" on purpose. A distinct error would
            # let anyone holding an id confirm that it belongs to someone else,
            # and payment ids travel through Telegram messages.
            raise PaymentNotFound("The payment was not found.", payment_id=payment_id)
        now = self._clock.now()

        if payment.is_expired_at(now):
            payment.expire()
            self._payments.save(payment)
            self._publish(payment)
            raise PaymentExpired(
                "The payment window for this invoice has expired.",
                payment_id=payment_id,
            )

        existing = self._payments.find_by_digest(proof.digest)
        if existing is not None and existing.id != payment.id:
            # Recorded as an event even though it is refused: one customer
            # doing this repeatedly is a fraud signal no single rejection
            # message conveys.
            self._events.publish_all(
                [
                    DuplicateReceiptDetected(
                        user_id=payment.user_id,
                        reference=proof.reference,
                        existing_payment_id=existing.id,
                    )
                ]
            )
            self._audit.record(
                action="payment.duplicate_receipt",
                actor_id=None,
                payment_id=payment.id,
                details={"existing": existing.id},
            )
            raise DuplicateReceipt(reference=proof.reference, existing_payment=existing.id)

        payment.attach_proof(proof)

        # Claimed in the same transaction as the proof it belongs to. The read
        # above closes the common case; this closes the race between two
        # submissions of the same photo, and it is the write that makes the
        # read able to find anything at all.
        if self._digests is not None:
            # Raises DuplicateReceipt if the digest is already claimed. The
            # translation happens in the repository, because the constraint
            # violation is a driver concern and this layer may not import one.
            self._digests.claim(
                proof.digest,
                payment_id=payment.id,
                user_id=payment.user_id,
                reference=proof.reference,
                method=payment.method.value,
                seen_at=now,
            )

        self._payments.save(payment)
        self._publish(payment)
        return payment

    # -- internals ---------------------------------------------------------

    def _proof_window(self, method: PaymentMethod) -> timedelta:
        # Imported lazily to keep the adapters module optional for callers
        # that register their own gateways.
        from geekvpn.application.payments.adapters import CARD_WINDOW, CRYPTO_WINDOW

        return CRYPTO_WINDOW if method is PaymentMethod.CRYPTO else CARD_WINDOW

    def _settle_free(self, *, invoice: Invoice, payment: Payment) -> None:
        """A fully discounted order still travels the whole pipeline."""
        now = self._clock.now()
        payment.approve(at=now, captured=Money(1))
        invoice.mark_paid(payment_id=payment.id, at=now)

    def _settle_from_wallet(self, *, invoice: Invoice, payment: Payment, amount: Money) -> None:
        """Debit the balance and approve in one step.

        The debit happens *before* approval. If the wallet cannot cover it,
        ``InsufficientFunds`` propagates and no payment is ever approved -
        which is the correct outcome, and the reason this ordering is not an
        accident.
        """
        now = self._clock.now()
        # Before the read, not after: two concurrent purchases can otherwise
        # both see the same balance, both pass the affordability check, and
        # both debit it. `lock` existed for exactly this and had no callers.
        self._wallets.lock(payment.user_id)
        wallet = self._wallets.get_or_create(payment.user_id)
        wallet.debit(
            amount,
            entry_id=self._ids.new_id(),
            kind=TransactionKind.PURCHASE,
            occurred_at=now,
            description_fa=invoice.subject_fa,
            reference=invoice.number,
        )
        self._wallets.save(wallet)

        payment.approve(at=now)
        invoice.mark_paid(payment_id=payment.id, at=now)
        self._publish(wallet)

    def _publish(self, *aggregates: object) -> None:
        collected: list[object] = []
        for aggregate in aggregates:
            collect = getattr(aggregate, "collect_events", None)
            if collect is not None:
                collected.extend(collect())
        if collected:
            self._events.publish_all(collected)


__all__ = ["CheckoutRequest", "CheckoutResult", "CheckoutService"]
