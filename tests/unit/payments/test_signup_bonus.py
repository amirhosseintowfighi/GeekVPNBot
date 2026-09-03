"""The welcome credit a new customer gets the first time they start the bot.

Money given by a rule rather than by a person, which is what `credit_reward`
was written for - and what nothing had ever called.

The tests that matter here are the ones about not paying twice. Everything else
is a preference; a second credit is real money leaving.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from geekvpn.application.payments.signup_bonus import KIND, REFERENCE, SignupBonusService
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.wallet import Wallet

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 3, tzinfo=UTC)
USER = 4242


class FakeLedger:
    def __init__(self) -> None:
        self.wallets: dict[int, Wallet] = {}

    def get_or_create(self, user_id: int) -> Wallet:
        return self.wallets.setdefault(user_id, Wallet(user_id))

    def save(self, wallet: Wallet) -> None:
        self.wallets[wallet.user_id] = wallet


class FakeWalletService:
    """Stands in for `WalletService.credit_reward`, recording what it was asked."""

    def __init__(self, ledger: FakeLedger) -> None:
        self._ledger = ledger
        self.calls: list[dict] = []
        self._next = 0

    def credit_reward(self, *, user_id, amount, kind, description_fa, reference=None):
        self.calls.append(
            {
                "user_id": user_id,
                "amount": amount,
                "kind": kind,
                "description_fa": description_fa,
                "reference": reference,
            }
        )
        self._next += 1
        wallet = self._ledger.get_or_create(user_id)
        entry = wallet.credit(
            amount,
            entry_id=f"e{self._next}",
            kind=kind,
            occurred_at=NOW,
            description_fa=description_fa,
            reference=reference,
        )
        self._ledger.save(wallet)
        return entry


def _service(*, reseller_id: str | None = None):
    ledger = FakeLedger()
    wallets = FakeWalletService(ledger)
    service = SignupBonusService(wallets=wallets, ledger=ledger, reseller_id=reseller_id)
    return service, wallets, ledger


def _grant(service, amount=50_000):
    return service.grant(user_id=USER, amount_toman=amount, note_fa="هدیهٔ خوش‌آمدگویی")


def test_a_new_customer_is_credited():
    service, _wallets, ledger = _service()

    entry = _grant(service)

    assert entry is not None
    assert ledger.get_or_create(USER).balance == Money(50_000)


def test_the_same_customer_is_never_credited_twice():
    """The one that matters. Everything else here is a preference."""
    service, wallets, _ = _service()

    first = _grant(service)
    second = _grant(service)

    assert first is not None
    assert second is None
    assert len(wallets.calls) == 1


def test_a_zero_amount_gives_nothing():
    """Zero is how the operator turns the bonus off, so it must not write a
    zero-value ledger entry that looks like a gift of nothing."""
    service, wallets, _ = _service()

    assert _grant(service, amount=0) is None
    assert wallets.calls == []


def test_a_negative_amount_never_takes_money_away():
    service, wallets, _ = _service()

    assert _grant(service, amount=-1000) is None
    assert wallets.calls == []


def test_a_resellers_customer_is_not_given_our_promotion():
    """The amount is our setting and the money would be theirs. Spending a
    reseller's margin on a promotion they never agreed to is not ours to do."""
    service, wallets, _ = _service(reseller_id="some-shop")

    assert _grant(service) is None
    assert wallets.calls == []


def test_it_is_recorded_so_it_can_be_recognised_later():
    """The reference is what the second attempt is refused by, and what the
    ledger's unique constraint enforces when two arrive at once."""
    service, wallets, _ = _service()

    _grant(service)

    assert wallets.calls[0]["reference"] == REFERENCE
    assert wallets.calls[0]["kind"] is KIND


def test_the_customer_sees_the_operators_own_wording():
    service, wallets, _ = _service()

    service.grant(user_id=USER, amount_toman=1000, note_fa="هدیه‌ی ما")

    assert wallets.calls[0]["description_fa"] == "هدیه‌ی ما"


def test_two_different_customers_each_get_one():
    service, wallets, _ = _service()

    service.grant(user_id=1, amount_toman=1000, note_fa="x")
    service.grant(user_id=2, amount_toman=1000, note_fa="x")

    assert len(wallets.calls) == 2
