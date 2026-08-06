"""Payment use cases.

One service per actor, because that is what actually differs:

* ``CheckoutService``      - the customer, starting a payment and sending proof.
* ``PaymentReviewService`` - the operator, approving or rejecting it.
* ``VerificationService``  - a background job, asking a gateway for an answer.
* ``RefundService``        - the operator, giving money back.
* ``WalletService``        - balances, statements and manual corrections.

Splitting by actor rather than by entity is what keeps the approval path free
of checkout concerns and the review queue free of gateway polling. A single
"PaymentService" would be all five of these with an audience of nobody.

Everything here is synchronous; see ``ports`` for why.
"""

from geekvpn.application.payments.adapters import (
    CARD_WINDOW,
    CRYPTO_WINDOW,
    CardTransferGateway,
    CryptoTransferGateway,
    WalletGateway,
)
from geekvpn.application.payments.checkout_service import (
    CheckoutRequest,
    CheckoutResult,
    CheckoutService,
)
from geekvpn.application.payments.ports import (
    Clock,
    EventPublisher,
    IdGenerator,
    InvoiceRepository,
    PaymentAuditLog,
    PaymentNotifier,
    PaymentRepository,
    ProvisioningService,
    WalletRepository,
)
from geekvpn.application.payments.refund_service import (
    RefundOutcome,
    RefundRequest,
    RefundService,
)
from geekvpn.application.payments.review_service import (
    ApprovalRequest,
    PaymentReviewService,
)
from geekvpn.application.payments.verification_service import (
    VerificationReport,
    VerificationService,
)
from geekvpn.application.payments.wallet_service import (
    TOPUP_PRESETS,
    Statement,
    WalletService,
)

__all__ = [
    "CARD_WINDOW",
    "CRYPTO_WINDOW",
    "TOPUP_PRESETS",
    "ApprovalRequest",
    "CardTransferGateway",
    "CheckoutRequest",
    "CheckoutResult",
    "CheckoutService",
    "Clock",
    "CryptoTransferGateway",
    "EventPublisher",
    "IdGenerator",
    "InvoiceRepository",
    "PaymentAuditLog",
    "PaymentNotifier",
    "PaymentRepository",
    "PaymentReviewService",
    "ProvisioningService",
    "RefundOutcome",
    "RefundRequest",
    "RefundService",
    "Statement",
    "VerificationReport",
    "VerificationService",
    "WalletGateway",
    "WalletRepository",
    "WalletService",
]
