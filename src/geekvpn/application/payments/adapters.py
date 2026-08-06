"""Manual payment adapters.

Card-to-card and crypto are modelled as **gateways whose verifier is a
human**. They implement exactly the same ``PaymentGateway`` protocol a real
provider will implement.

That is the single most valuable decision in the payment system. It means the
day Zarinpal is switched on, the checkout service, the bot keyboards, the
admin queue and the refund logic do not change: a new adapter is registered
and a new key appears. Nothing above the registry knows the difference.

``verify`` on a manual adapter always answers ``INCONCLUSIVE``. That is not a
stub - it is the truth. Only a human can confirm a card receipt, so the
automatic verifier correctly declines to guess, and the sweeper leaves the
payment in the review queue where it belongs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import (
    PaymentMethod,
    RefundDestination,
    VerificationOutcome,
)
from geekvpn.domain.payments.gateway import (
    MANUAL_CAPABILITIES,
    CheckoutInstruction,
    GatewayCapabilities,
    RefundResult,
    VerificationResult,
)

CARD_WINDOW: Final[timedelta] = timedelta(hours=6)
"""A card receipt may arrive after a night's sleep."""

CRYPTO_WINDOW: Final[timedelta] = timedelta(minutes=90)
"""Much shorter, because a quoted crypto rate cannot be honoured for hours.
The customer is told this figure explicitly rather than discovering it."""


@dataclass(slots=True)
class CardTransferGateway:
    """Card-to-card, approved by hand.

    The destination card is passed in rather than hard-coded: these rotate
    frequently in the Iranian market, and a rotation must be a settings change
    rather than a deployment.
    """

    card_number: str
    card_holder_fa: str
    bank_name_fa: str
    key: str = "card"
    title_fa: str = "\u06a9\u0627\u0631\u062a \u0628\u0647 \u06a9\u0627\u0631\u062a"
    method: PaymentMethod = PaymentMethod.CARD
    capabilities: GatewayCapabilities = MANUAL_CAPABILITIES

    def begin(
        self,
        *,
        payment_id: str,
        amount: Money,
        user_id: int,
        invoice_number: str,
        callback_url: str | None = None,
    ) -> CheckoutInstruction:
        # The invoice number goes in the transfer description so a reviewer
        # can match a receipt to an order without asking the customer.
        instructions = (
            "\u0645\u0628\u0644\u063a \u0631\u0627 \u0628\u0647 \u06a9\u0627\u0631\u062a \u0632\u06cc\u0631 \u0648\u0627\u0631\u06cc\u0632 \u06a9\u0646\u06cc\u062f \u0648 "
            "\u0633\u067e\u0633 \u062a\u0635\u0648\u06cc\u0631 \u0631\u0633\u06cc\u062f \u0631\u0627 \u0627\u0631\u0633\u0627\u0644 \u06a9\u0646\u06cc\u062f."
        )
        return CheckoutInstruction(
            payment_id=payment_id,
            method=PaymentMethod.CARD,
            amount=amount,
            instructions_fa=instructions,
            metadata={
                "card_number": self.card_number,
                "card_holder_fa": self.card_holder_fa,
                "bank_name_fa": self.bank_name_fa,
                "invoice_number": invoice_number,
            },
        )

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        """Never confirms. A photograph is not machine-verifiable."""
        return VerificationResult(
            outcome=VerificationOutcome.INCONCLUSIVE,
            message_fa=(
                "\u0631\u0633\u06cc\u062f \u06a9\u0627\u0631\u062a \u0628\u0647 \u06a9\u0627\u0631\u062a \u0641\u0642\u0637 "
                "\u062a\u0648\u0633\u0637 \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc \u0628\u0631\u0631\u0633\u06cc \u0645\u06cc\u200c\u0634\u0648\u062f."
            ),
        )

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        """Declines rather than raising, so the caller falls back to the wallet."""
        return RefundResult(
            succeeded=False,
            destination=RefundDestination.WALLET,
            message_fa=(
                "\u0628\u0627\u0632\u06af\u0634\u062a \u0648\u062c\u0647 \u06a9\u0627\u0631\u062a \u0628\u0647 \u06a9\u0627\u0631\u062a "
                "\u0628\u0647 \u0635\u0648\u0631\u062a \u062e\u0648\u062f\u06a9\u0627\u0631 \u0645\u0645\u06a9\u0646 \u0646\u06cc\u0633\u062a."
            ),
        )


@dataclass(slots=True)
class CryptoTransferGateway:
    """On-chain transfer identified by a transaction hash.

    Verification is manual today but the shape is already right for a chain
    explorer: ``verify`` receives the hash and the expected amount, and the
    only change needed later is to answer ``CONFIRMED`` instead of
    ``INCONCLUSIVE``. No caller changes.
    """

    address: str
    network: str
    key: str = "crypto"
    title_fa: str = (
        "\u067e\u0631\u062f\u0627\u062e\u062a \u0628\u0627 \u0631\u0645\u0632\u0627\u0631\u0632"
    )
    method: PaymentMethod = PaymentMethod.CRYPTO
    capabilities: GatewayCapabilities = MANUAL_CAPABILITIES

    def begin(
        self,
        *,
        payment_id: str,
        amount: Money,
        user_id: int,
        invoice_number: str,
        callback_url: str | None = None,
    ) -> CheckoutInstruction:
        return CheckoutInstruction(
            payment_id=payment_id,
            method=PaymentMethod.CRYPTO,
            amount=amount,
            address=self.address,
            network=self.network,
            instructions_fa=(
                "\u067e\u0633 \u0627\u0632 \u0627\u0646\u062a\u0642\u0627\u0644\u060c \u0634\u0646\u0627\u0633\u0647\u0654 "
                "\u062a\u0631\u0627\u06a9\u0646\u0634 (TXID) \u0631\u0627 \u0627\u0631\u0633\u0627\u0644 \u06a9\u0646\u06cc\u062f."
            ),
            metadata={"invoice_number": invoice_number},
        )

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        return VerificationResult(
            outcome=VerificationOutcome.INCONCLUSIVE,
            reference=reference,
            retry_after=timedelta(minutes=5),
            message_fa=(
                "\u062a\u0631\u0627\u06a9\u0646\u0634 \u062f\u0631 \u0627\u0646\u062a\u0638\u0627\u0631 "
                "\u0628\u0631\u0631\u0633\u06cc \u0627\u0633\u062a."
            ),
        )

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        return RefundResult(
            succeeded=False,
            destination=RefundDestination.WALLET,
            message_fa=(
                "\u0628\u0627\u0632\u06af\u0634\u062a \u0631\u0645\u0632\u0627\u0631\u0632 "
                "\u0628\u0647 \u0635\u0648\u0631\u062a \u062e\u0648\u062f\u06a9\u0627\u0631 \u0645\u0645\u06a9\u0646 \u0646\u06cc\u0633\u062a."
            ),
        )


@dataclass(slots=True)
class WalletGateway:
    """Paying from an existing balance.

    Included in the registry so that "pay with wallet" is not a special case
    branching around the whole payment system. It settles immediately, needs
    no proof, and refunds perfectly - the money never left.
    """

    key: str = "wallet"
    title_fa: str = "\u06a9\u06cc\u0641 \u067e\u0648\u0644"
    method: PaymentMethod = PaymentMethod.WALLET
    # GatewayCapabilities is frozen, so one shared instance cannot be mutated by
    # a caller. RUF009 guards against mutable defaults, which this is not.
    capabilities: GatewayCapabilities = GatewayCapabilities(  # noqa: RUF009
        supports_auto_verification=True,
        supports_online_refund=True,
        supports_partial_refund=True,
        requires_redirect=False,
        requires_manual_review=False,
    )

    def begin(
        self,
        *,
        payment_id: str,
        amount: Money,
        user_id: int,
        invoice_number: str,
        callback_url: str | None = None,
    ) -> CheckoutInstruction:
        return CheckoutInstruction(
            payment_id=payment_id, method=PaymentMethod.WALLET, amount=amount
        )

    def verify(self, *, payment_id: str, reference: str, expected: Money) -> VerificationResult:
        # The debit already succeeded or the purchase never happened.
        return VerificationResult(outcome=VerificationOutcome.CONFIRMED, amount=expected)

    def refund(self, *, payment_id: str, reference: str, amount: Money) -> RefundResult:
        return RefundResult(succeeded=True, destination=RefundDestination.WALLET)


__all__ = [
    "CARD_WINDOW",
    "CRYPTO_WINDOW",
    "CardTransferGateway",
    "CryptoTransferGateway",
    "WalletGateway",
]
