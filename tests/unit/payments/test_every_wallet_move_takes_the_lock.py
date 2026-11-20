"""Every movement of a customer's wallet holds the wallet lock first.

Checkout, top-ups and transfers took the advisory lock before reading the
balance; an operator's adjustment, a bulk adjustment and a reward did not.
Each entry carries the balance after it, computed from the wallet as read -
so an operator's deduction landing beside a purchase read the same balance,
both passed, and the wallet went below zero with two entries that each claim
a positive balance. A reward beside a purchase wrote a balance that was
already wrong by the price of the purchase.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from geekvpn.application.payments.wallet_service import WalletService
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import TransactionKind
from tests.unit.payments.fakes import FakeWallets

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 20, tzinfo=UTC)


class _Wallets(FakeWallets):
    """Records whether the lock came before the balance was read."""

    def __init__(self) -> None:
        super().__init__()
        self.read_unlocked: list[int] = []

    def get_or_create(self, user_id: int):
        if user_id not in self.locked:
            self.read_unlocked.append(user_id)
        return super().get_or_create(user_id)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Ids:
    def __init__(self) -> None:
        self.n = 0

    def new_id(self) -> str:
        self.n += 1
        return f"e{self.n}"


class _Events:
    def publish(self, *_: object) -> None:
        pass

    def publish_all(self, *_: object) -> None:
        pass


class _Audit:
    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *a, **k: None


def _service(wallets: _Wallets) -> WalletService:
    return WalletService(
        wallets=wallets,  # type: ignore[arg-type]
        clock=_Clock(),
        ids=_Ids(),
        events=_Events(),  # type: ignore[arg-type]
        audit=_Audit(),  # type: ignore[arg-type]
    )


def test_an_operator_adjustment_locks_before_reading() -> None:
    wallets = _Wallets()

    _service(wallets).adjust(
        user_id=7, signed_amount=50_000, actor_id=1, reason_fa="هدیه‌ی جشنواره‌ی پاییز"
    )

    assert wallets.locked == [7]
    assert wallets.read_unlocked == []


def test_a_bulk_deduction_locks_before_reading_the_balance_it_caps_at() -> None:
    wallets = _Wallets()
    service = _service(wallets)
    service.adjust(user_id=7, signed_amount=50_000, actor_id=1, reason_fa="هدیه‌ی جشنواره‌ی پاییز")
    wallets.locked.clear()

    service.adjust_many(
        user_ids=[7], signed_amount=-80_000, actor_id=1, reason_fa="برگشت هدیه‌ی اشتباهی"
    )

    assert wallets.locked and wallets.locked[0] == 7
    assert wallets.read_unlocked == []


def test_a_reward_locks_before_reading() -> None:
    wallets = _Wallets()

    _service(wallets).credit_reward(
        user_id=7, amount=Money(10_000), kind=TransactionKind.CASHBACK, description_fa="پاداش"
    )

    assert wallets.locked == [7]
    assert wallets.read_unlocked == []
