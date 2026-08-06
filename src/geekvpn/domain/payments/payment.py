"""The payment aggregate.

This is where double-charging is prevented, so it is written defensively on
purpose.

Three decisions shape the file:

1. **Transitions are declared as data, not scattered through methods.**
   ``_ALLOWED`` is the whole state machine in one readable block. A reviewer
   can check it against the business rules in ten seconds; the same rules
   spread across nine ``if`` statements cannot be checked at all.

2. **Refunds are entries, never a mutated amount.** ``captured`` never
   changes. Refunding appends to a list and the refundable balance is derived.
   That way a partially refunded payment still reports honestly what was
   originally taken, which is what reconciliation against a bank statement
   needs.

3. **Approval is the only door to provisioning**, and it can be walked through
   exactly once. The second concurrent approver hits
   ``IllegalPaymentTransition`` rather than creating a second subscription.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import (
    PaymentMethod,
    PaymentState,
    RefundDestination,
    RefundReason,
)
from geekvpn.domain.payments.errors import (
    IllegalPaymentTransition,
    PaymentValidationError,
    RefundExceedsPayment,
    RefundNotAllowed,
)
from geekvpn.domain.payments.events import (
    PaymentApproved,
    PaymentExpiredEvent,
    PaymentFailed,
    PaymentInitiated,
    PaymentRefunded,
    PaymentRejected,
    ProofSubmitted,
)
from geekvpn.domain.payments.proof import PaymentProof

MIN_REASON_LENGTH: Final[int] = 5
"""Same floor as the admin panel. A rejection reason reaches the customer
verbatim, so "no" is not acceptable."""

DEFAULT_PROOF_WINDOW: Final[timedelta] = timedelta(hours=6)
"""How long a card payment waits for a receipt before expiring.

Long enough to survive a night's sleep, short enough that the pending queue
reflects reality. Crypto uses a shorter window set by the application layer,
because a quoted exchange rate cannot be honoured for six hours.
"""


_ALLOWED: Final[Mapping[PaymentState, frozenset[PaymentState]]] = {
    PaymentState.DRAFT: frozenset(
        {
            PaymentState.AWAITING_PROOF,
            PaymentState.PENDING_GATEWAY,
            PaymentState.APPROVED,  # wallet and zero-total invoices settle at once
            PaymentState.EXPIRED,
            PaymentState.FAILED,
        }
    ),
    PaymentState.AWAITING_PROOF: frozenset(
        {
            PaymentState.PENDING_REVIEW,
            PaymentState.EXPIRED,
            PaymentState.REJECTED,
        }
    ),
    PaymentState.PENDING_REVIEW: frozenset(
        {
            PaymentState.APPROVED,
            PaymentState.REJECTED,
            # Back to the customer when the receipt is unreadable rather than
            # fraudulent. Rejecting an honest customer over a blurred photo
            # loses the sale; asking again does not.
            PaymentState.AWAITING_PROOF,
        }
    ),
    PaymentState.PENDING_GATEWAY: frozenset(
        {
            PaymentState.APPROVED,
            PaymentState.FAILED,
            PaymentState.EXPIRED,
            # A gateway that reports an amount mismatch hands the decision to
            # a human rather than silently failing.
            PaymentState.PENDING_REVIEW,
        }
    ),
    PaymentState.APPROVED: frozenset({PaymentState.REFUNDED, PaymentState.PARTIALLY_REFUNDED}),
    PaymentState.PARTIALLY_REFUNDED: frozenset({PaymentState.REFUNDED}),
    # Terminal.
    PaymentState.REJECTED: frozenset(),
    PaymentState.REFUNDED: frozenset(),
    PaymentState.EXPIRED: frozenset(),
    PaymentState.FAILED: frozenset(),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class RefundEntry:
    """One returned amount. Immutable; several may exist per payment."""

    refund_id: str
    amount: int
    reason: RefundReason
    destination: RefundDestination
    note_fa: str
    refunded_at: datetime
    actor_id: int | None

    def __post_init__(self) -> None:
        if self.amount <= 0:
            raise PaymentValidationError("A refund must be for a positive amount.")


class Payment(AggregateRoot[str]):
    """One attempt to settle one invoice."""

    __slots__ = (
        "_captured",
        "_refunds",
        "_state",
        "amount",
        "created_at",
        "expires_at",
        "failure_reason",
        "gateway_key",
        "gateway_reference",
        "invoice_id",
        "metadata",
        "method",
        "proof",
        "rejection_reason_fa",
        "reviewed_at",
        "reviewed_by",
        "settled_at",
        "user_id",
    )

    def __init__(
        self,
        payment_id: str,
        *,
        invoice_id: str,
        user_id: int,
        method: PaymentMethod,
        amount: Money,
        created_at: datetime,
        state: PaymentState = PaymentState.DRAFT,
        expires_at: datetime | None = None,
        gateway_key: str | None = None,
        gateway_reference: str | None = None,
        proof: PaymentProof | None = None,
        captured: int = 0,
        refunds: Sequence[RefundEntry] = (),
        settled_at: datetime | None = None,
        reviewed_at: datetime | None = None,
        reviewed_by: int | None = None,
        rejection_reason_fa: str | None = None,
        failure_reason: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        super().__init__(payment_id)
        if amount.amount <= 0:
            raise PaymentValidationError(
                "A payment must be for a positive amount.", amount=amount.amount
            )
        if method is PaymentMethod.GATEWAY and not gateway_key:
            # Without this the seam leaks: a gateway payment with no provider
            # cannot be verified, refunded, or reconciled later.
            raise PaymentValidationError("A gateway payment must name the gateway it went through.")

        self.invoice_id = invoice_id
        self.user_id = user_id
        self.method = method
        self.amount = amount
        self._state = state
        self._captured = captured
        self._refunds: list[RefundEntry] = list(refunds)
        self.proof = proof
        self.gateway_key = gateway_key
        self.gateway_reference = gateway_reference
        self.created_at = created_at
        self.expires_at = expires_at
        self.settled_at = settled_at
        self.reviewed_at = reviewed_at
        self.reviewed_by = reviewed_by
        self.rejection_reason_fa = rejection_reason_fa
        self.failure_reason = failure_reason
        self.metadata: dict[str, str] = dict(metadata or {})

    # -- construction ------------------------------------------------------

    @classmethod
    def start(
        cls,
        payment_id: str,
        *,
        invoice_id: str,
        user_id: int,
        method: PaymentMethod,
        amount: Money,
        created_at: datetime,
        expires_at: datetime | None = None,
        gateway_key: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Payment:
        payment = cls(
            payment_id,
            invoice_id=invoice_id,
            user_id=user_id,
            method=method,
            amount=amount,
            created_at=created_at,
            expires_at=expires_at,
            gateway_key=gateway_key,
            metadata=metadata,
        )
        payment.record(
            PaymentInitiated(
                payment_id=payment_id,
                invoice_id=invoice_id,
                user_id=user_id,
                method=str(method),
                amount=amount.amount,
            )
        )
        return payment

    # -- reading -----------------------------------------------------------

    @property
    def state(self) -> PaymentState:
        return self._state

    @property
    def captured(self) -> Money:
        """What was actually taken. Never reduced by refunds."""
        return Money(self._captured)

    @property
    def refunds(self) -> tuple[RefundEntry, ...]:
        return tuple(self._refunds)

    @property
    def refunded_total(self) -> Money:
        return Money(sum(entry.amount for entry in self._refunds))

    @property
    def refundable(self) -> Money:
        """What is still returnable."""
        if not self._state.is_settled():
            return Money.zero()
        return Money(max(0, self._captured - self.refunded_total.amount))

    @property
    def is_refundable(self) -> bool:
        return self.refundable.amount > 0

    def can_transition_to(self, target: PaymentState) -> bool:
        return target in _ALLOWED[self._state]

    def is_expired_at(self, now: datetime) -> bool:
        if self.expires_at is None or self._state.is_terminal():
            return False
        return now >= self.expires_at

    def waiting_minutes(self, now: datetime) -> int:
        """How long a human has owed this customer an answer.

        Measured from proof submission, not from creation. The admin queue is
        sorted by this, and a customer who took two days to send a receipt has
        not been waiting on *us* for two days.
        """
        if self.proof is None:
            return 0
        started = self.proof.submitted_at
        reference = self.reviewed_at or now
        return max(0, int((reference - started).total_seconds() // 60))

    # -- transitions -------------------------------------------------------

    def _transition(self, target: PaymentState) -> None:
        if target not in _ALLOWED[self._state]:
            raise IllegalPaymentTransition(current=str(self._state), target=str(target))
        self._state = target

    def await_proof(self, *, expires_at: datetime | None = None) -> None:
        """Tell the customer we are waiting on a receipt or a hash."""
        if not self.method.needs_proof():
            raise PaymentValidationError(
                "This payment method does not require proof.",
                method=str(self.method),
            )
        self._transition(PaymentState.AWAITING_PROOF)
        if expires_at is not None:
            self.expires_at = expires_at

    def send_to_gateway(self, *, gateway_key: str, reference: str) -> None:
        """Record that the customer was handed off to an external provider."""
        self._transition(PaymentState.PENDING_GATEWAY)
        self.gateway_key = gateway_key
        self.gateway_reference = reference

    def attach_proof(self, proof: PaymentProof) -> None:
        """Accept a receipt or a transaction hash and join the review queue.

        Duplicate detection is *not* done here: this aggregate cannot see
        other payments. The application layer checks the digest against the
        repository before calling, which is the only place with that view.
        """
        if proof.method is not self.method:
            raise PaymentValidationError(
                "The proof does not match the chosen payment method.",
                expected=str(self.method),
                actual=str(proof.method),
            )
        self._transition(PaymentState.PENDING_REVIEW)
        self.proof = proof
        self.record(
            ProofSubmitted(
                payment_id=self.id,
                user_id=self.user_id,
                method=str(self.method),
                reference=proof.reference,
            )
        )

    def flag_for_review(self) -> None:
        """Hand a gateway payment to a human.

        Needed when a provider confirms an amount that does not match the
        invoice. There is no proof object to attach - the customer submitted
        nothing - so this is a bare transition into the review queue rather
        than a re-use of ``attach_proof``, which would emit a misleading
        ``ProofSubmitted`` event for proof that never existed.
        """
        self._transition(PaymentState.PENDING_REVIEW)

    def request_better_proof(self) -> None:
        """Send an unreadable receipt back without rejecting the payment."""
        self._transition(PaymentState.AWAITING_PROOF)
        self.proof = None

    def approve(
        self,
        *,
        at: datetime,
        approved_by: int | None = None,
        captured: Money | None = None,
    ) -> None:
        """Capture the money. The only path to provisioning.

        ``captured`` may differ from ``amount`` when a gateway or a chain
        confirms a different figure. The application layer decides whether
        that difference is acceptable; by the time we are here the decision
        has been made, and what we store is what really arrived.
        """
        self._transition(PaymentState.APPROVED)
        self._captured = (captured or self.amount).amount
        self.settled_at = at
        self.reviewed_at = at
        self.reviewed_by = approved_by
        self.record(
            PaymentApproved(
                payment_id=self.id,
                invoice_id=self.invoice_id,
                user_id=self.user_id,
                method=str(self.method),
                amount=self._captured,
                approved_by=approved_by,
            )
        )

    def reject(self, *, at: datetime, reason_fa: str, rejected_by: int | None = None) -> None:
        """Decline a manual payment. The reason reaches the customer verbatim."""
        cleaned = reason_fa.strip()
        if len(cleaned) < MIN_REASON_LENGTH:
            raise PaymentValidationError(
                "A rejection needs a written reason.", minimum=MIN_REASON_LENGTH
            )
        self._transition(PaymentState.REJECTED)
        self.rejection_reason_fa = cleaned
        self.reviewed_at = at
        self.reviewed_by = rejected_by
        self.record(
            PaymentRejected(
                payment_id=self.id,
                user_id=self.user_id,
                reason_fa=cleaned,
                rejected_by=rejected_by,
            )
        )

    def fail(self, *, reason: str) -> None:
        """A gateway attempt died. The customer may start a fresh attempt."""
        self._transition(PaymentState.FAILED)
        self.failure_reason = reason
        self.record(PaymentFailed(payment_id=self.id, user_id=self.user_id, reason=reason))

    def expire(self) -> None:
        """Close the window. Called by a sweeper, never by a customer action."""
        self._transition(PaymentState.EXPIRED)
        self.record(PaymentExpiredEvent(payment_id=self.id, user_id=self.user_id))

    # -- refunds -----------------------------------------------------------

    def refund(
        self,
        amount: Money,
        *,
        refund_id: str,
        reason: RefundReason,
        destination: RefundDestination,
        note_fa: str,
        at: datetime,
        actor_id: int | None = None,
    ) -> RefundEntry:
        """Return money, in whole or in part.

        Partial refunds are supported because the common real case is not
        "undo the sale" but "we owe them three days of an outage".

        The state lands on ``PARTIALLY_REFUNDED`` until the refundable balance
        reaches zero, at which point it becomes ``REFUNDED`` and terminal.
        This is what stops the same payment being refunded twice by two
        operators: the second call finds a refundable balance of zero.
        """
        if not self._state.is_settled():
            raise RefundNotAllowed(
                "Only a settled payment can be refunded.",
                state=str(self._state),
            )
        if len(note_fa.strip()) < MIN_REASON_LENGTH:
            raise PaymentValidationError(
                "A refund needs a written reason.", minimum=MIN_REASON_LENGTH
            )

        remaining = self.refundable.amount
        if amount.amount > remaining:
            raise RefundExceedsPayment(requested=amount.amount, refundable=remaining)

        entry = RefundEntry(
            refund_id=refund_id,
            amount=amount.amount,
            reason=reason,
            destination=destination,
            note_fa=note_fa.strip(),
            refunded_at=at,
            actor_id=actor_id,
        )
        self._refunds.append(entry)

        fully = self.refundable.amount == 0
        target = PaymentState.REFUNDED if fully else PaymentState.PARTIALLY_REFUNDED
        if target is not self._state:
            self._transition(target)

        self.record(
            PaymentRefunded(
                payment_id=self.id,
                user_id=self.user_id,
                amount=amount.amount,
                remaining=self.refundable.amount,
                reason=str(reason),
                destination=str(destination),
                refunded_by=actor_id,
            )
        )
        return entry


__all__ = [
    "DEFAULT_PROOF_WINDOW",
    "MIN_REASON_LENGTH",
    "Payment",
    "RefundEntry",
]
