"""Three features that were fully written and never called.

Each had a domain method, a repository method, or both - with zero callers. The
code read as complete, the tests exercised the pieces in isolation, and the
behaviour did not exist.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime

import pytest

from geekvpn.application.payments.topups import (
    TOPUP_METADATA_KEY,
    TOPUP_METADATA_VALUE,
    credit_topup,
    is_topup,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.invoice import Invoice, InvoiceLine

NOW = datetime(2026, 8, 19, tzinfo=UTC)


def make_invoice(*, topup: bool, amount: int = 500_000) -> Invoice:
    return Invoice.issue(
        "inv-1",
        number="GV-1405-000001",
        user_id=555,
        subject_fa="شارژ کیف پول" if topup else "خرید سرویس",
        lines=[InvoiceLine(title_fa="مبلغ", amount=amount)],
        issued_at=NOW,
        metadata={TOPUP_METADATA_KEY: TOPUP_METADATA_VALUE} if topup else {},
    )


class RecordingWallets:
    def __init__(self) -> None:
        self.locked: list[int] = []
        self.saved: list[object] = []
        self._wallets: dict[int, object] = {}

    def lock(self, user_id: int) -> None:
        self.locked.append(user_id)

    def get_or_create(self, user_id: int):
        from geekvpn.domain.payments.wallet import Wallet

        return self._wallets.setdefault(user_id, Wallet(user_id))

    def save(self, wallet: object) -> None:
        self.saved.append(wallet)


# -- 9: a settled top-up must credit the wallet ---------------------------


def test_a_topup_invoice_is_recognised() -> None:
    assert is_topup(make_invoice(topup=True))
    assert not is_topup(make_invoice(topup=False))


def test_settling_a_topup_credits_the_principal() -> None:
    """The whole point of a top-up, and nothing performed it: `Wallet.top_up`
    had zero callers while `begin_topup` tagged every invoice for it."""
    wallets = RecordingWallets()

    wallet = credit_topup(
        make_invoice(topup=True),
        wallets=wallets,  # type: ignore[arg-type]
        amount=Money(500_000),
        entry_id=str(uuid.uuid4()),
        now=NOW,
    )

    assert wallet is not None
    assert wallet.balance.amount == 500_000
    assert wallets.saved


def test_a_purchase_invoice_credits_nothing() -> None:
    """Buying a plan must not also hand the customer the money back."""
    wallets = RecordingWallets()

    wallet = credit_topup(
        make_invoice(topup=False),
        wallets=wallets,  # type: ignore[arg-type]
        amount=Money(500_000),
        entry_id=str(uuid.uuid4()),
        now=NOW,
    )

    assert wallet is None
    assert wallets.saved == []


def test_the_credit_is_referenced_by_invoice_number() -> None:
    """uq_wallet_user_kind_reference is what makes a second approval of the
    same invoice unable to credit twice, so the reference has to be stable."""
    wallets = RecordingWallets()
    invoice = make_invoice(topup=True)

    wallet = credit_topup(
        invoice,
        wallets=wallets,  # type: ignore[arg-type]
        amount=Money(500_000),
        entry_id=str(uuid.uuid4()),
        now=NOW,
    )

    assert wallet is not None
    assert wallet.entries[-1].reference == invoice.number


def test_the_wallet_is_locked_before_the_credit() -> None:
    wallets = RecordingWallets()

    credit_topup(
        make_invoice(topup=True),
        wallets=wallets,  # type: ignore[arg-type]
        amount=Money(500_000),
        entry_id=str(uuid.uuid4()),
        now=NOW,
    )

    assert wallets.locked == [555]


@pytest.mark.parametrize("service", ["review_service", "verification_service"])
def test_both_settlement_paths_credit_topups(service: str) -> None:
    """A top-up that credits on one path and not the other is worse than one
    that credits on neither, because it looks like it works."""
    module = __import__(f"geekvpn.application.payments.{service}", fromlist=["x"])

    assert "credit_topup" in inspect.getsource(module)


@pytest.mark.parametrize("service", ["review_service", "verification_service"])
def test_an_overpaid_topup_keeps_both_credits(service: str) -> None:
    """The surplus branch must reuse the loaded aggregate. Re-reading would
    discard the top-up entry and credit only the overpayment."""
    module = __import__(f"geekvpn.application.payments.{service}", fromlist=["x"])
    source = inspect.getsource(module)

    assert "wallet = wallet or self._wallets.get_or_create" in source


# -- 10: the receipt digest must actually be written ----------------------


def test_checkout_claims_the_digest_it_later_reads() -> None:
    """`find_by_digest` read a table nothing wrote, so the duplicate-receipt
    guard could only ever miss."""
    from geekvpn.application.payments.checkout_service import CheckoutService

    source = inspect.getsource(CheckoutService.submit_proof)

    assert "_digests.claim(" in source
    assert source.index("attach_proof(") < source.index("_digests.claim("), (
        "the claim belongs in the same transaction as the proof"
    )


def test_the_repository_translates_the_constraint_violation() -> None:
    """The application layer may not import a driver exception, so the
    translation has to happen in infrastructure."""
    from geekvpn.infrastructure.persistence.repositories.sync_payments import (
        SyncReceiptDigestRepository,
    )

    source = inspect.getsource(SyncReceiptDigestRepository)

    assert "IntegrityError" in source
    assert "DuplicateReceipt" in source


def test_the_digest_repository_is_wired_into_the_scope() -> None:
    """Written but unreachable is the failure mode this whole audit is about."""
    from geekvpn.infrastructure.di import sync_scope

    source = inspect.getsource(sync_scope)

    assert "SyncReceiptDigestRepository" in source
    assert "digests=self.receipt_digests" in source


# -- 13: coupon limits ----------------------------------------------------


def test_placing_an_order_records_the_coupon_redemption() -> None:
    """`Coupon.redeem` and `record_redemption` both had zero callers, so
    max_redemptions and max_per_user were decorative."""
    from geekvpn.infrastructure.bot.checkout import BotCheckoutAdapter

    source = inspect.getsource(BotCheckoutAdapter)

    assert "_record_coupon_use" in source
    assert "record_redemption(" in source
    assert "coupon.redeem(" in source


def test_first_purchase_is_read_from_history_not_assumed() -> None:
    """Defaulted to False, a first-purchase-only coupon never expires for
    anyone and returning customers are priced as new ones."""
    from geekvpn.infrastructure.bot.checkout import BotCheckoutAdapter

    source = inspect.getsource(BotCheckoutAdapter._begin)

    assert "has_completed_order" in source
    assert "is_first_purchase=is_first" in source


def test_the_redemption_shares_the_order_transaction() -> None:
    """Recorded outside it, the redemption is either lost with a rolled-back
    order or survives an order that never existed."""
    from geekvpn.infrastructure.bot.checkout import BotCheckoutAdapter

    source = inspect.getsource(BotCheckoutAdapter._begin)

    assert source.index("_orders.place(") < source.index("_record_coupon_use(")
