"""The wallet ledger.

The invariant worth defending: the balance is *derived*, never stored. Every
test here is ultimately checking that a replay of the entries and the recorded
running total say the same thing.
"""

from __future__ import annotations

from datetime import timedelta

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import TransactionKind
from geekvpn.domain.payments.errors import InsufficientFunds, PaymentValidationError
from geekvpn.domain.payments.wallet import (
    MAX_TOPUP,
    MIN_ADJUSTMENT_REASON,
    MIN_TOPUP,
    Wallet,
)
from tests.unit.payments.fakes import EPOCH

REASON_FA = (
    "\u0627\u0635\u0644\u0627\u062d \u062f\u0633\u062a\u06cc \u0645\u0648\u062c\u0648\u062f\u06cc"
)
TOPUP_FA = "\u0634\u0627\u0631\u0698"


def _wallet(user_id: int = 555) -> Wallet:
    return Wallet(user_id)


def _credit(wallet: Wallet, amount: int, *, entry_id: str = "e1", offset: int = 0):
    return wallet.credit(
        Money(amount),
        entry_id=entry_id,
        kind=TransactionKind.TOPUP,
        occurred_at=EPOCH + timedelta(minutes=offset),
        description_fa=TOPUP_FA,
    )


def test_new_wallet_is_empty_not_missing():
    wallet = _wallet()
    assert wallet.balance == Money(0)
    assert wallet.entries == ()


def test_credit_then_debit_tracks_running_balance():
    wallet = _wallet()
    _credit(wallet, 500_000, entry_id="e1")
    wallet.debit(
        Money(180_000),
        entry_id="e2",
        kind=TransactionKind.PURCHASE,
        occurred_at=EPOCH + timedelta(minutes=1),
        description_fa="\u062e\u0631\u06cc\u062f",
    )
    assert wallet.balance == Money(320_000)
    assert [entry.balance_after for entry in wallet.entries] == [500_000, 320_000]


def test_balance_is_derived_so_replay_agrees_with_the_witness():
    wallet = _wallet()
    _credit(wallet, 300_000, entry_id="e1")
    _credit(wallet, 200_000, entry_id="e2", offset=1)
    assert wallet.recompute_balance() == wallet.balance.amount
    assert wallet.entries[-1].balance_after == wallet.recompute_balance()


def test_debit_beyond_balance_is_refused_with_the_shortfall():
    wallet = _wallet()
    _credit(wallet, 100_000, entry_id="e1")
    try:
        wallet.debit(
            Money(250_000),
            entry_id="e2",
            kind=TransactionKind.PURCHASE,
            occurred_at=EPOCH,
            description_fa="\u062e\u0631\u06cc\u062f",
        )
    except InsufficientFunds as error:
        # The gap is carried on the error so the bot can pre-fill a top-up
        # instead of making the customer subtract two numbers.
        assert error.details["shortfall"] == 150_000
    else:
        raise AssertionError("an overdraft was allowed")

    # And nothing was written: a refused debit leaves no trace in the ledger.
    assert wallet.balance == Money(100_000)
    assert len(wallet.entries) == 1


def test_shortfall_for_is_zero_when_affordable():
    wallet = _wallet()
    _credit(wallet, 100_000, entry_id="e1")
    assert wallet.can_afford(Money(100_000)) is True
    assert wallet.shortfall_for(Money(100_000)) == Money(0)
    assert wallet.shortfall_for(Money(130_000)) == Money(30_000)


def test_zero_and_negative_movements_are_refused():
    wallet = _wallet()
    for amount in (Money(0),):
        try:
            _credit(wallet, amount.amount)
        except PaymentValidationError:
            pass
        else:
            raise AssertionError("a zero credit was accepted")


def test_topup_enforces_its_bounds_in_the_aggregate():
    wallet = _wallet()
    for amount in (MIN_TOPUP - 1, MAX_TOPUP + 1):
        try:
            wallet.top_up(Money(amount), entry_id="e1", occurred_at=EPOCH)
        except PaymentValidationError:
            pass
        else:
            raise AssertionError(f"{amount} passed the top-up bounds")

    entry = wallet.top_up(Money(MIN_TOPUP), entry_id="e2", occurred_at=EPOCH)
    assert entry.kind is TransactionKind.TOPUP
    assert wallet.balance == Money(MIN_TOPUP)


def test_adjustment_requires_an_actor_and_a_real_reason():
    wallet = _wallet()
    try:
        wallet.adjust(
            50_000, entry_id="e1", occurred_at=EPOCH, reason_fa="\u062e\u0637", actor_id=7
        )
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("an unexplained adjustment was accepted")

    assert len(REASON_FA) >= MIN_ADJUSTMENT_REASON
    entry = wallet.adjust(50_000, entry_id="e2", occurred_at=EPOCH, reason_fa=REASON_FA, actor_id=7)
    assert entry.actor_id == 7
    assert entry.kind is TransactionKind.ADJUSTMENT
    assert entry.description_fa == REASON_FA


def test_adjustment_of_zero_is_meaningless_and_refused():
    wallet = _wallet()
    try:
        wallet.adjust(0, entry_id="e1", occurred_at=EPOCH, reason_fa=REASON_FA, actor_id=7)
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("a zero adjustment was accepted")


def test_negative_adjustment_cannot_push_the_balance_below_zero():
    wallet = _wallet()
    _credit(wallet, 40_000, entry_id="e1")
    try:
        wallet.adjust(
            -100_000,
            entry_id="e2",
            occurred_at=EPOCH,
            reason_fa=REASON_FA,
            actor_id=7,
        )
    except InsufficientFunds:
        pass
    else:
        raise AssertionError("an operator drove a wallet negative")
    assert wallet.balance == Money(40_000)


def test_refund_credit_records_the_operator_who_issued_it():
    # Regression: RefundService passes actor_id when crediting a refund. If
    # credit() does not accept it, every wallet refund fails at runtime.
    wallet = _wallet()
    entry = wallet.credit(
        Money(120_000),
        entry_id="e1",
        kind=TransactionKind.REFUND,
        occurred_at=EPOCH,
        description_fa="\u0628\u0627\u0632\u06af\u0634\u062a \u0648\u062c\u0647",
        reference="inv-1",
        actor_id=42,
    )
    assert entry.actor_id == 42


def test_history_is_newest_first_and_filterable():
    wallet = _wallet()
    _credit(wallet, 100_000, entry_id="e1", offset=0)
    wallet.debit(
        Money(30_000),
        entry_id="e2",
        kind=TransactionKind.PURCHASE,
        occurred_at=EPOCH + timedelta(minutes=5),
        description_fa="\u062e\u0631\u06cc\u062f",
    )
    newest_first = wallet.history()
    assert [entry.entry_id for entry in newest_first] == ["e2", "e1"]

    purchases = wallet.history(kind=TransactionKind.PURCHASE)
    assert [entry.entry_id for entry in purchases] == ["e2"]


def test_adjustment_is_excluded_from_is_credit():
    # Its direction comes from the sign at the call site, never from the kind.
    assert TransactionKind.ADJUSTMENT.is_credit() is False
    assert TransactionKind.OVERPAYMENT.is_credit() is True
    assert TransactionKind.PURCHASE.is_credit() is False
