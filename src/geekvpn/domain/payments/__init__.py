"""Payments bounded context.

Wallets, invoices, payments, proofs, refunds and the gateway seam.

Nothing in this package touches the network, a database, or a clock it did not
receive as an argument. Every rule that decides whether money may move lives
here and is pure, which is why the payment tests need no fixtures and no fakes
beyond a datetime.

Where to look:

* ``enums``    - the vocabulary, including the payment state machine.
* ``wallet``   - a balance derived from an append-only ledger, never stored.
* ``payment``  - one attempt to pay one invoice; owns its own transitions.
* ``proof``    - receipts and transaction hashes, fingerprinted so the same
                 evidence cannot be spent twice.
* ``invoice``  - the immutable document; voided and reissued, never edited.
* ``gateway``  - the seam future online providers plug into. Manual card and
                 crypto implement the same protocol, so the seam is exercised
                 today rather than discovered to be wrong later.
* ``events``   - what the rest of the system learns after money moves.
"""

from geekvpn.domain.payments.enums import (
    InvoiceState,
    PaymentMethod,
    PaymentState,
    RefundDestination,
    RefundReason,
    TransactionKind,
    VerificationOutcome,
)
from geekvpn.domain.payments.errors import (
    AmountMismatch,
    DuplicateReceipt,
    GatewayError,
    GatewayNotRegistered,
    IllegalPaymentTransition,
    InsufficientFunds,
    InvoiceNotFound,
    PaymentError,
    PaymentExpired,
    PaymentNotFound,
    PaymentValidationError,
    RefundExceedsPayment,
    RefundNotAllowed,
    VerificationFailed,
)
from geekvpn.domain.payments.events import (
    DuplicateReceiptDetected,
    InvoiceIssued,
    PaymentApproved,
    PaymentExpiredEvent,
    PaymentFailed,
    PaymentInitiated,
    PaymentRefunded,
    PaymentRejected,
    ProofSubmitted,
    WalletCredited,
    WalletDebited,
)
from geekvpn.domain.payments.gateway import (
    MANUAL_CAPABILITIES,
    CheckoutInstruction,
    GatewayCapabilities,
    GatewayRegistry,
    PaymentGateway,
    RefundResult,
    VerificationResult,
)
from geekvpn.domain.payments.invoice import (
    INVOICE_PREFIX,
    Invoice,
    InvoiceLine,
    format_invoice_number,
)
from geekvpn.domain.payments.payment import (
    DEFAULT_PROOF_WINDOW,
    MIN_REASON_LENGTH,
    Payment,
    RefundEntry,
)
from geekvpn.domain.payments.proof import (
    MAX_NOTE_LENGTH,
    MAX_TXID_LENGTH,
    MIN_TXID_LENGTH,
    PaymentProof,
    fingerprint,
    normalise_reference,
)
from geekvpn.domain.payments.wallet import (
    MAX_TOPUP,
    MIN_ADJUSTMENT_REASON,
    MIN_TOPUP,
    LedgerEntry,
    Wallet,
)

__all__ = [
    "DEFAULT_PROOF_WINDOW",
    "INVOICE_PREFIX",
    "MANUAL_CAPABILITIES",
    "MAX_NOTE_LENGTH",
    "MAX_TOPUP",
    "MAX_TXID_LENGTH",
    "MIN_ADJUSTMENT_REASON",
    "MIN_REASON_LENGTH",
    "MIN_TOPUP",
    "MIN_TXID_LENGTH",
    "AmountMismatch",
    "CheckoutInstruction",
    "DuplicateReceipt",
    "DuplicateReceiptDetected",
    "GatewayCapabilities",
    "GatewayError",
    "GatewayNotRegistered",
    "GatewayRegistry",
    "IllegalPaymentTransition",
    "InsufficientFunds",
    "Invoice",
    "InvoiceIssued",
    "InvoiceLine",
    "InvoiceNotFound",
    "InvoiceState",
    "LedgerEntry",
    "Payment",
    "PaymentApproved",
    "PaymentError",
    "PaymentExpired",
    "PaymentExpiredEvent",
    "PaymentFailed",
    "PaymentGateway",
    "PaymentInitiated",
    "PaymentMethod",
    "PaymentNotFound",
    "PaymentProof",
    "PaymentRefunded",
    "PaymentRejected",
    "PaymentState",
    "PaymentValidationError",
    "ProofSubmitted",
    "RefundDestination",
    "RefundEntry",
    "RefundExceedsPayment",
    "RefundNotAllowed",
    "RefundReason",
    "RefundResult",
    "TransactionKind",
    "VerificationFailed",
    "VerificationOutcome",
    "VerificationResult",
    "Wallet",
    "WalletCredited",
    "WalletDebited",
    "fingerprint",
    "format_invoice_number",
    "normalise_reference",
]
