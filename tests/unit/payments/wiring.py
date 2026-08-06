"""One assembled set of services over shared fakes.

Every service test needs the same eight collaborators wired the same way.
Building them inline in each test buries the one line that matters.
"""

from __future__ import annotations

from dataclasses import dataclass

from geekvpn.application.payments.adapters import (
    CardTransferGateway,
    CryptoTransferGateway,
    WalletGateway,
)
from geekvpn.application.payments.checkout_service import CheckoutService
from geekvpn.application.payments.refund_service import RefundService
from geekvpn.application.payments.review_service import PaymentReviewService
from geekvpn.application.payments.verification_service import VerificationService
from geekvpn.application.payments.wallet_service import WalletService
from geekvpn.domain.payments.gateway import GatewayRegistry
from tests.unit.payments.fakes import (
    FakeAudit,
    FakeClock,
    FakeEvents,
    FakeIds,
    FakeInvoices,
    FakePayments,
    FakeWallets,
)

CARD_NUMBER = "6037-9911-2233-4455"
HOLDER_FA = "\u0627\u0645\u06cc\u0631 \u062a\u0648\u0641\u06cc\u0642\u06cc"
BANK_FA = "\u0645\u0644\u06cc"


@dataclass
class World:
    clock: FakeClock
    ids: FakeIds
    events: FakeEvents
    audit: FakeAudit
    wallets: FakeWallets
    payments: FakePayments
    invoices: FakeInvoices
    gateways: GatewayRegistry
    checkout: CheckoutService
    review: PaymentReviewService
    refunds: RefundService
    verification: VerificationService
    wallet_service: WalletService


def build_world() -> World:
    clock = FakeClock()
    ids = FakeIds()
    events = FakeEvents()
    audit = FakeAudit()
    wallets = FakeWallets()
    payments = FakePayments()
    invoices = FakeInvoices()

    gateways = GatewayRegistry()
    gateways.register(
        CardTransferGateway(card_number=CARD_NUMBER, card_holder_fa=HOLDER_FA, bank_name_fa=BANK_FA)
    )
    gateways.register(CryptoTransferGateway(address="T9yD...", network="trc20"))
    gateways.register(WalletGateway())

    common = {
        "clock": clock,
        "ids": ids,
        "events": events,
        "audit": audit,
    }
    return World(
        clock=clock,
        ids=ids,
        events=events,
        audit=audit,
        wallets=wallets,
        payments=payments,
        invoices=invoices,
        gateways=gateways,
        checkout=CheckoutService(
            invoices=invoices,
            payments=payments,
            wallets=wallets,
            gateways=gateways,
            **common,
        ),
        review=PaymentReviewService(
            payments=payments, invoices=invoices, wallets=wallets, **common
        ),
        refunds=RefundService(
            payments=payments,
            invoices=invoices,
            wallets=wallets,
            gateways=gateways,
            **common,
        ),
        verification=VerificationService(
            payments=payments,
            invoices=invoices,
            wallets=wallets,
            gateways=gateways,
            **common,
        ),
        wallet_service=WalletService(wallets=wallets, **common),
    )


__all__ = ["BANK_FA", "CARD_NUMBER", "HOLDER_FA", "World", "build_world"]
