"""A fully assembled payment system built from fakes.

Shared by the service tests so each one asserts on behaviour rather than on
wiring. Everything is real except the four ports that touch the outside world.
"""

from __future__ import annotations

from geekvpn.application.payments.adapters import (
    CardTransferGateway,
    CryptoTransferGateway,
    WalletGateway,
)
from geekvpn.application.payments.checkout_service import (
    CheckoutRequest,
    CheckoutService,
)
from geekvpn.application.payments.refund_service import RefundService
from geekvpn.application.payments.review_service import PaymentReviewService
from geekvpn.application.payments.verification_service import VerificationService
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import TransactionKind
from geekvpn.domain.payments.gateway import GatewayRegistry
from geekvpn.domain.payments.invoice import InvoiceLine
from tests.unit.payments.fakes import (
    EPOCH,
    FakeAudit,
    FakeClock,
    FakeEvents,
    FakeIds,
    FakeInvoices,
    FakePayments,
    FakeWallets,
)

PLAN = "\u067e\u0644\u0646 \u06af\u06cc\u06a9 \u062a\u0648\u0631\u0628\u0648"
USER = 1001


class World:
    def __init__(self) -> None:
        self.clock = FakeClock()
        self.ids = FakeIds()
        self.events = FakeEvents()
        self.audit = FakeAudit()
        self.wallets = FakeWallets()
        self.payments = FakePayments()
        self.invoices = FakeInvoices()

        self.gateways = GatewayRegistry()
        self.gateways.register(WalletGateway())
        self.gateways.register(
            CardTransferGateway(
                card_number="6037-9911",
                card_holder_fa="\u0639\u0644\u06cc",
                bank_name_fa="\u0645\u0644\u06cc",
            )
        )
        self.gateways.register(CryptoTransferGateway(address="TXyz", network="trc20"))

        common = {
            "payments": self.payments,
            "invoices": self.invoices,
            "wallets": self.wallets,
            "clock": self.clock,
            "ids": self.ids,
            "events": self.events,
            "audit": self.audit,
        }
        self.checkout = CheckoutService(gateways=self.gateways, **common)
        self.review = PaymentReviewService(**common)
        self.refunds = RefundService(gateways=self.gateways, **common)
        self.verification = VerificationService(gateways=self.gateways, **common)

    # -- helpers -----------------------------------------------------------

    def fund(self, amount: int, user_id: int = USER) -> None:
        wallet = self.wallets.get_or_create(user_id)
        wallet.credit(
            Money(amount),
            entry_id=f"seed-{amount}",
            kind=TransactionKind.TOPUP,
            occurred_at=EPOCH,
            description_fa="\u0634\u0627\u0631\u0698",
        )
        self.wallets.save(wallet)

    def buy(self, *, gateway_key: str = "card", amount: int = 680_000):
        return self.checkout.begin(
            CheckoutRequest(
                user_id=USER,
                subject_fa=PLAN,
                lines=[InvoiceLine(title_fa=PLAN, amount=amount)],
                gateway_key=gateway_key,
                jalali_year=1405,
            )
        )

    def balance(self, user_id: int = USER) -> int:
        return self.wallets.get_or_create(user_id).balance.amount


__all__ = ["EPOCH", "PLAN", "USER", "World"]
