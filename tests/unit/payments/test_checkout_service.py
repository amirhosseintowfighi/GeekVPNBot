"""Checkout: invoice issuing, wallet settlement, and duplicate receipts.

These are the paths where two aggregates must move together, so the fakes are
asserted on end state (a balance, an invoice state) rather than on calls.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from geekvpn.application.payments.adapters import (
    CARD_WINDOW,
    CRYPTO_WINDOW,
    CardTransferGateway,
    CryptoTransferGateway,
    WalletGateway,
)
from geekvpn.application.payments.checkout_service import (
    CheckoutRequest,
    CheckoutService,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import (
    InvoiceState,
    PaymentState,
    TransactionKind,
)
from geekvpn.domain.payments.errors import (
    DuplicateReceipt,
    InsufficientFunds,
    PaymentExpired,
    PaymentValidationError,
)
from geekvpn.domain.payments.gateway import GatewayRegistry
from geekvpn.domain.payments.invoice import InvoiceLine
from geekvpn.domain.payments.proof import PaymentProof
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


class World:
    """One assembled service plus everything needed to assert on it."""

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
        self.service = CheckoutService(
            invoices=self.invoices,
            payments=self.payments,
            wallets=self.wallets,
            gateways=self.gateways,
            clock=self.clock,
            ids=self.ids,
            events=self.events,
            audit=self.audit,
        )

    def buy(self, *, gateway_key: str = "card", amount: int = 680_000, discount: int = 0):
        lines = [InvoiceLine(title_fa=PLAN, amount=amount)]
        if discount:
            lines.append(InvoiceLine(title_fa="\u062a\u062e\u0641\u06cc\u0641", amount=-discount))
        return self.service.begin(
            CheckoutRequest(
                user_id=1001,
                subject_fa=PLAN,
                lines=lines,
                gateway_key=gateway_key,
                jalali_year=1405,
            )
        )

    def fund(self, amount: int) -> None:
        wallet = self.wallets.get_or_create(1001)
        wallet.credit(
            Money(amount),
            entry_id="seed",
            kind=TransactionKind.TOPUP,
            occurred_at=EPOCH,
            description_fa="\u0634\u0627\u0631\u0698",
        )
        self.wallets.save(wallet)


def test_checkout_issues_a_numbered_invoice():
    result = World().buy()
    assert result.invoice.number == "GV-1405-000001"
    assert result.invoice.state is InvoiceState.OPEN


def test_invoice_numbers_increment_per_year():
    world = World()
    first = world.buy()
    second = world.buy()
    assert first.invoice.number == "GV-1405-000001"
    assert second.invoice.number == "GV-1405-000002"


def test_a_card_checkout_waits_for_a_receipt_with_a_deadline():
    result = World().buy(gateway_key="card")
    assert result.payment.state is PaymentState.AWAITING_PROOF
    assert result.payment.expires_at == EPOCH + CARD_WINDOW
    assert result.instruction.expires_at == EPOCH + CARD_WINDOW
    assert not result.settled


def test_crypto_gets_a_shorter_window_than_card():
    """A quoted crypto rate cannot be honoured for six hours."""
    assert CRYPTO_WINDOW < CARD_WINDOW
    result = World().buy(gateway_key="crypto")
    assert result.payment.expires_at == EPOCH + CRYPTO_WINDOW


def test_the_card_instruction_tells_the_customer_where_to_send_money():
    result = World().buy(gateway_key="card")
    assert result.instruction.metadata["card_number"] == "6037-9911"
    assert result.instruction.instructions_fa


def test_paying_from_the_wallet_settles_immediately():
    world = World()
    world.fund(1_000_000)
    result = world.buy(gateway_key="wallet")
    assert result.settled
    assert result.invoice.state is InvoiceState.PAID
    assert world.wallets.get_or_create(1001).balance.amount == 320_000


def test_a_wallet_purchase_locks_the_wallet_before_reading_it():
    """The guard against a double-spend.

    Two concurrent purchases could otherwise both read the same balance, both
    pass the affordability check, and both debit it - leaving a negative
    balance for the CHECK constraint to reject later, against a customer who
    has already been given two services.
    """
    world = World()
    world.fund(1_000_000)

    world.buy(gateway_key="wallet")

    assert world.wallets.locked == [1001]


def test_a_purchase_paid_another_way_does_not_lock_the_wallet():
    """The lock is only warranted where the balance is actually spent."""
    world = World()
    world.fund(1_000_000)

    world.buy(gateway_key="card")

    assert world.wallets.locked == []


def test_a_wallet_purchase_appears_in_the_ledger():
    world = World()
    world.fund(1_000_000)
    world.buy(gateway_key="wallet")
    entries = world.wallets.get_or_create(1001).history(kind=TransactionKind.PURCHASE)
    assert len(entries) == 1
    assert entries[0].amount == -680_000


def test_an_unaffordable_wallet_purchase_approves_nothing():
    """The debit happens before approval precisely so this cannot half-happen."""
    world = World()
    world.fund(100_000)
    with pytest.raises(InsufficientFunds):
        world.buy(gateway_key="wallet")
    assert world.wallets.get_or_create(1001).balance.amount == 100_000
    assert not any(p.state is PaymentState.APPROVED for p in world.payments.rows.values())


def test_a_fully_discounted_order_still_travels_the_whole_pipeline():
    """Provisioning listens to PaymentApproved and nothing else.

    A free order that skips the payment system is a free order that never
    provisions.
    """
    world = World()
    result = world.buy(gateway_key="card", discount=680_000)
    assert result.invoice.is_free
    assert result.settled
    assert result.invoice.state is InvoiceState.PAID
    assert "PaymentApproved" in world.events.names()


def test_checkout_publishes_the_invoice_issued_event():
    world = World()
    world.buy()
    assert "InvoiceIssued" in world.events.names()


def test_checkout_is_audited():
    world = World()
    world.buy()
    assert "payment.begin" in world.audit.actions()


def test_submitting_a_receipt_moves_the_payment_into_review():
    world = World()
    result = world.buy(gateway_key="card")
    payment = world.service.submit_proof(
        payment_id=result.payment.id,
        proof=PaymentProof.for_card(file_id="f1", image_digest="aaa", submitted_at=EPOCH),
    )
    assert payment.state is PaymentState.PENDING_REVIEW
    assert payment.state.awaits_operator()


def test_a_receipt_already_used_on_another_order_is_refused():
    """The commonest card-to-card fraud: forward one genuine receipt."""
    world = World()
    first = world.buy(gateway_key="card")
    second = world.buy(gateway_key="card")
    world.service.submit_proof(
        payment_id=first.payment.id,
        proof=PaymentProof.for_card(file_id="f1", image_digest="same-bytes", submitted_at=EPOCH),
    )
    with pytest.raises(DuplicateReceipt):
        world.service.submit_proof(
            payment_id=second.payment.id,
            proof=PaymentProof.for_card(
                file_id="f2-forwarded", image_digest="same-bytes", submitted_at=EPOCH
            ),
        )
    assert second.payment.state is PaymentState.AWAITING_PROOF


def test_a_duplicate_is_recorded_even_though_it_is_refused():
    """One customer doing this repeatedly is a signal no single rejection shows."""
    world = World()
    first = world.buy(gateway_key="card")
    second = world.buy(gateway_key="card")
    world.service.submit_proof(
        payment_id=first.payment.id,
        proof=PaymentProof.for_card(file_id="f1", image_digest="same", submitted_at=EPOCH),
    )
    with pytest.raises(DuplicateReceipt):
        world.service.submit_proof(
            payment_id=second.payment.id,
            proof=PaymentProof.for_card(file_id="f2", image_digest="same", submitted_at=EPOCH),
        )
    assert world.events.of("DuplicateReceiptDetected")
    assert "payment.duplicate_receipt" in world.audit.actions()


def test_resubmitting_the_same_receipt_to_the_same_payment_is_not_a_duplicate():
    """Re-sending your own receipt after a request for a clearer photo."""
    world = World()
    result = world.buy(gateway_key="card")
    proof = PaymentProof.for_card(file_id="f1", image_digest="mine", submitted_at=EPOCH)
    world.service.submit_proof(payment_id=result.payment.id, proof=proof)
    result.payment.request_better_proof()
    world.service.submit_proof(payment_id=result.payment.id, proof=proof)
    assert result.payment.state is PaymentState.PENDING_REVIEW


def test_a_receipt_arriving_after_the_window_is_refused_and_the_payment_expires():
    world = World()
    result = world.buy(gateway_key="card")
    world.clock.advance(CARD_WINDOW + timedelta(minutes=1))
    with pytest.raises(PaymentExpired):
        world.service.submit_proof(
            payment_id=result.payment.id,
            proof=PaymentProof.for_card(
                file_id="f1", image_digest="late", submitted_at=world.clock.now()
            ),
        )
    assert result.payment.state is PaymentState.EXPIRED


def test_a_topup_below_the_minimum_is_refused():
    world = World()
    with pytest.raises(PaymentValidationError):
        world.service.begin_topup(
            user_id=1001,
            amount=Money(10_000),
            gateway_key="card",
            jalali_year=1405,
        )


def test_a_wallet_cannot_be_topped_up_from_itself():
    world = World()
    with pytest.raises(PaymentValidationError):
        world.service.begin_topup(
            user_id=1001,
            amount=Money(500_000),
            gateway_key="wallet",
            jalali_year=1405,
        )


def test_a_topup_produces_an_ordinary_invoice():
    world = World()
    result = world.service.begin_topup(
        user_id=1001, amount=Money(500_000), gateway_key="card", jalali_year=1405
    )
    assert result.invoice.total.amount == 500_000
    assert result.invoice.metadata["kind"] == "topup"
    assert result.payment.state is PaymentState.AWAITING_PROOF
