"""Payment vocabulary.

Stored as string values, never ordinals, for the same reason as the catalog
enums: reordering members must never rewrite the meaning of historical rows.
A payment row from eight months ago has to keep meaning what it meant.
"""

from __future__ import annotations

import enum


class PaymentMethod(enum.StrEnum):
    """How the customer moves money to us.

    ``CARD`` and ``CRYPTO`` are what exist today. ``GATEWAY`` is the seam for
    the online providers we will add later: it is a *single* member rather
    than one per provider, because the provider name is data (see
    ``Payment.gateway_key``), not a type. Adding Zarinpal must not require a
    migration of this enum.
    """

    WALLET = "wallet"
    """Paid from an existing balance. Settles instantly; no verification."""

    CARD = "card"
    """Card-to-card transfer with a photographed receipt, approved by a human."""

    CRYPTO = "crypto"
    """On-chain transfer identified by a transaction hash."""

    GATEWAY = "gateway"
    """Online provider redirect. Verified automatically, never by hand."""

    CREDIT = "credit"
    """Granted by an operator: compensation, goodwill, a migrated balance.

    A first-class method rather than a fake card payment, so that revenue
    reporting can exclude money that never entered a bank account.
    """

    def is_manual(self) -> bool:
        """Whether a human must look at this before it settles."""
        return self in {PaymentMethod.CARD, PaymentMethod.CRYPTO}

    def needs_proof(self) -> bool:
        """Whether the customer must submit something for us to check."""
        return self in {PaymentMethod.CARD, PaymentMethod.CRYPTO}


class PaymentState(enum.StrEnum):
    """The lifecycle of one attempt to pay one invoice.

    The states are deliberately about *money*, not about UI. ``PENDING_REVIEW``
    means a human owes the customer an answer; ``AWAITING_PROOF`` means the
    customer owes us one. Collapsing those two into a single "pending" is how
    support queues end up full of tickets nobody can triage.
    """

    DRAFT = "draft"
    """Invoice created, method not chosen yet. No money is in flight."""

    AWAITING_PROOF = "awaiting_proof"
    """We are waiting on the customer: a receipt photo or a tx hash."""

    PENDING_REVIEW = "pending_review"
    """Proof submitted. **We** are the bottleneck now."""

    PENDING_GATEWAY = "pending_gateway"
    """Customer sent to a provider; awaiting the callback or a poll."""

    APPROVED = "approved"
    """Money captured. This is the ONLY state that may provision a service."""

    REJECTED = "rejected"
    """Reviewed and declined. Terminal. Requires a written reason."""

    REFUNDED = "refunded"
    """Fully returned. Terminal."""

    PARTIALLY_REFUNDED = "partially_refunded"
    """Some money returned, some retained. NOT terminal: more may follow."""

    EXPIRED = "expired"
    """The payment window closed before proof arrived. Terminal."""

    FAILED = "failed"
    """The gateway declined or errored out. Terminal for this attempt only;
    the customer may start a new one against the same invoice."""

    def is_terminal(self) -> bool:
        return self in _TERMINAL

    def is_settled(self) -> bool:
        """Whether money has actually been captured.

        A partially refunded payment is still settled: we are holding part of
        it, and the subscription it bought stays alive.
        """
        return self in {
            PaymentState.APPROVED,
            PaymentState.PARTIALLY_REFUNDED,
        }

    def awaits_customer(self) -> bool:
        return self in {PaymentState.AWAITING_PROOF, PaymentState.PENDING_GATEWAY}

    def awaits_operator(self) -> bool:
        return self is PaymentState.PENDING_REVIEW


_TERMINAL: frozenset[PaymentState] = frozenset(
    {
        PaymentState.REJECTED,
        PaymentState.REFUNDED,
        PaymentState.EXPIRED,
        PaymentState.FAILED,
    }
)


class InvoiceState(enum.StrEnum):
    """The lifecycle of what is *owed*, as distinct from what was *paid*.

    An invoice can outlive several payments: a customer whose card receipt was
    rejected may pay the same invoice again in crypto. Keeping the two
    aggregates separate is what makes that possible without inventing a
    second invoice and double-counting revenue.
    """

    OPEN = "open"
    PAID = "paid"
    VOID = "void"
    """Cancelled before payment. Never deleted: the number was issued."""

    REFUNDED = "refunded"


class TransactionKind(enum.StrEnum):
    """Why money moved in or out of a wallet.

    Every wallet balance change has exactly one of these. There is no generic
    "other": an unexplainable ledger entry is a bug, and naming it forces the
    question at write time rather than at audit time.
    """

    TOPUP = "topup"
    PURCHASE = "purchase"
    REFUND = "refund"
    CASHBACK = "cashback"
    REFERRAL_REWARD = "referral_reward"
    ADJUSTMENT = "adjustment"
    """Manual operator correction. Always carries a reason and an actor."""

    OVERPAYMENT = "overpayment"
    """Surplus from a payment that exceeded its invoice.

    Distinct from a top-up because the customer did not intend it, and
    distinct from cashback because it is their own money, not a reward.
    """

    def is_credit(self) -> bool:
        """Whether this kind normally increases the balance.

        ``ADJUSTMENT`` is excluded on purpose: it is the one kind that can go
        either way, so its direction must come from the amount's sign at the
        call site rather than from its kind.
        """
        return self in {
            TransactionKind.TOPUP,
            TransactionKind.REFUND,
            TransactionKind.CASHBACK,
            TransactionKind.REFERRAL_REWARD,
            TransactionKind.OVERPAYMENT,
        }


class RefundReason(enum.StrEnum):
    """Why money went back.

    Reported on separately from the amount, because "we refunded 12M Toman
    this month" is meaningless while "9M of it was failed provisioning" is an
    engineering priority.
    """

    CUSTOMER_REQUEST = "customer_request"
    SERVICE_FAILURE = "service_failure"
    """We could not deliver: panel down, provisioning failed."""

    DUPLICATE_PAYMENT = "duplicate_payment"
    FRAUD = "fraud"
    GOODWILL = "goodwill"


class RefundDestination(enum.StrEnum):
    """Where refunded money lands.

    Defaulting to the wallet is deliberate commercial policy: it is instant,
    it costs no bank fee, it requires no card number from the customer, and
    the money usually returns to us as a future purchase. Bank returns are
    supported because a customer who wants out deserves out.
    """

    WALLET = "wallet"
    ORIGINAL = "original"
    """Back to the source: gateway reversal, or a manual bank transfer."""


class VerificationOutcome(enum.StrEnum):
    """The result of trying to confirm a payment automatically.

    ``INCONCLUSIVE`` is the important member. A crypto transaction with one
    confirmation is neither confirmed nor false; treating it as either is
    wrong. It means "ask again later".
    """

    CONFIRMED = "confirmed"
    DECLINED = "declined"
    INCONCLUSIVE = "inconclusive"
    MISMATCH = "mismatch"
    """Confirmed, but not for the amount we invoiced."""


__all__ = [
    "InvoiceState",
    "PaymentMethod",
    "PaymentState",
    "RefundDestination",
    "RefundReason",
    "TransactionKind",
    "VerificationOutcome",
]
