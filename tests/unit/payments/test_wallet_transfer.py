"""A customer moving wallet balance to another customer of the same shop."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from geekvpn.application.payments.wallet_service import WalletService
from geekvpn.application.payments.wallet_transfer import WalletTransfers
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import TransactionKind
from geekvpn.domain.payments.errors import InsufficientFunds, WalletTransferRefused
from geekvpn.domain.payments.wallet import Wallet

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
ALICE, BOB, STRANGER = 100, 200, 300


class _Wallets:
    def __init__(self) -> None:
        self.rows: dict[int, Wallet] = {}
        self.locked: list[int] = []

    def get_or_create(self, user_id: int) -> Wallet:
        return self.rows.setdefault(user_id, Wallet(user_id))

    def save(self, wallet: Wallet) -> None:
        self.rows[wallet.user_id] = wallet

    def lock(self, user_id: int) -> None:
        self.locked.append(user_id)


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
    def __init__(self) -> None:
        self.published: list[object] = []

    def publish_all(self, events: list[object]) -> None:
        self.published.extend(events)


class _Audit:
    def record(self, **_: object) -> None:
        pass


def _build(*, enabled: bool = True, minimum: int = 10_000, balance: int = 100_000):
    wallets = _Wallets()
    service = WalletService(
        wallets=wallets,  # type: ignore[arg-type]
        clock=_Clock(),
        ids=_Ids(),
        events=_Events(),  # type: ignore[arg-type]
        audit=_Audit(),  # type: ignore[arg-type]
    )
    if balance:
        wallet = wallets.get_or_create(ALICE)
        wallet.credit(
            Money(balance),
            entry_id="seed",
            kind=TransactionKind.TOPUP,
            occurred_at=NOW,
            description_fa="شارژ",
        )
        wallet.collect_events()
    reports: list[tuple[int, int, int]] = []
    transfers = WalletTransfers(
        wallets=service,
        is_customer=lambda user_id: user_id in (ALICE, BOB),
        enabled=lambda: enabled,
        minimum_toman=lambda: minimum,
        report=lambda a, b, amount: reports.append((a, b, amount)),
    )
    return transfers, wallets, reports


def test_the_amount_leaves_one_wallet_and_arrives_in_the_other() -> None:
    transfers, wallets, _ = _build()

    transfers.transfer(from_user=ALICE, to_user=BOB, amount_toman=30_000)

    assert wallets.rows[ALICE].balance == Money(70_000)
    assert wallets.rows[BOB].balance == Money(30_000)


def test_both_sides_are_labelled_as_a_transfer_with_one_reference() -> None:
    transfers, wallets, _ = _build()

    transfers.transfer(from_user=ALICE, to_user=BOB, amount_toman=30_000)

    out = wallets.rows[ALICE].entries[-1]
    into = wallets.rows[BOB].entries[-1]
    assert (out.kind, into.kind) == (TransactionKind.TRANSFER_OUT, TransactionKind.TRANSFER_IN)
    assert out.reference == into.reference is not None


def test_both_wallets_are_locked_in_a_fixed_order() -> None:
    """Two people sending to each other at once must not deadlock."""
    transfers, wallets, _ = _build()

    transfers.transfer(from_user=ALICE, to_user=BOB, amount_toman=30_000)

    assert wallets.locked == sorted([ALICE, BOB])


def test_the_operator_is_told_who_sent_how_much_to_whom() -> None:
    transfers, _, reports = _build()

    transfers.transfer(from_user=ALICE, to_user=BOB, amount_toman=30_000)

    assert reports == [(ALICE, BOB, 30_000)]


def test_more_than_the_balance_is_refused_and_nothing_moves() -> None:
    transfers, wallets, reports = _build(balance=20_000)

    with pytest.raises(InsufficientFunds):
        transfers.transfer(from_user=ALICE, to_user=BOB, amount_toman=30_000)
    assert wallets.rows[ALICE].balance == Money(20_000)
    assert BOB not in wallets.rows or wallets.rows[BOB].balance == Money(0)
    assert reports == []


@pytest.mark.parametrize(
    ("to_user", "amount", "enabled"),
    [
        (BOB, 30_000, False),  # switched off
        (BOB, 5_000, True),  # under the minimum
        (ALICE, 30_000, True),  # to themselves
        (STRANGER, 30_000, True),  # not a customer of this shop
    ],
)
def test_a_transfer_the_shop_does_not_allow_is_refused(
    to_user: int, amount: int, enabled: bool
) -> None:
    transfers, wallets, _ = _build(enabled=enabled)

    with pytest.raises(WalletTransferRefused):
        transfers.transfer(from_user=ALICE, to_user=to_user, amount_toman=amount)
    assert wallets.rows[ALICE].balance == Money(100_000)
