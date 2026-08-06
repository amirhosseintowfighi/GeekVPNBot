"""The customer wallet.

One rule shapes this entire file: **the balance is not a field that gets
assigned, it is the sum of the ledger.** Every mutation appends an immutable
entry and recomputes. A wallet whose balance can be set directly is a wallet
whose history will eventually disagree with its number, and when a customer
asks "where did my 200,000 go?" the only acceptable answer is a list of rows.

The second rule: **entries carry a signed amount, but Money never does.**
``Money`` refuses to be negative by design, so direction lives in the entry.
That keeps an accidental sign flip from silently inverting a purchase into a
credit.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import TransactionKind
from geekvpn.domain.payments.errors import (
    InsufficientFunds,
    PaymentValidationError,
)
from geekvpn.domain.payments.events import WalletCredited, WalletDebited

MIN_TOPUP: Final[int] = 50_000
MAX_TOPUP: Final[int] = 50_000_000
"""Matches the bot and Mini App exactly. A limit enforced in one layer only is
a limit a determined user routes around."""

MIN_ADJUSTMENT_REASON: Final[int] = 5
"""Same five characters the admin panel demands. "ok" is not an audit trail."""


@dataclass(frozen=True, slots=True, kw_only=True)
class LedgerEntry:
    """One immutable movement of money.

    ``balance_after`` is stored rather than derived at read time. It is
    redundant by construction, and that redundancy is the point: it lets any
    single row be audited in isolation, and it makes a corrupted sequence
    detectable instead of merely wrong.
    """

    entry_id: str
    kind: TransactionKind
    amount: int
    """Signed. Positive credits the customer, negative debits them."""

    balance_after: int
    occurred_at: datetime
    description_fa: str
    reference: str | None = None
    """Payment id, invoice number, or order reference this entry belongs to."""

    actor_id: int | None = None
    """Operator who caused it. Set only for manual adjustments."""

    def __post_init__(self) -> None:
        if self.amount == 0:
            raise PaymentValidationError("A ledger entry cannot be for zero.")
        if self.balance_after < 0:
            raise PaymentValidationError(
                "A wallet balance can never be negative.",
                balance_after=self.balance_after,
            )

    @property
    def is_credit(self) -> bool:
        return self.amount > 0


class Wallet(AggregateRoot[int]):
    """A customer's balance, identified by their user id.

    Deliberately keyed by user rather than by a wallet id. A customer has
    exactly one wallet in one currency; inventing a separate identifier would
    add a join and a class of "which wallet?" bugs to buy nothing.
    """

    __slots__ = ("_balance", "_entries")

    def __init__(self, user_id: int, entries: Sequence[LedgerEntry] = ()) -> None:
        super().__init__(user_id)
        self._entries: list[LedgerEntry] = list(entries)
        self._balance: int = self._entries[-1].balance_after if self._entries else 0

    # -- reading -----------------------------------------------------------

    @property
    def user_id(self) -> int:
        return self.id

    @property
    def balance(self) -> Money:
        return Money(self._balance)

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def can_afford(self, amount: Money) -> bool:
        return self._balance >= amount.amount

    def shortfall_for(self, amount: Money) -> Money:
        """How much is missing. Zero when affordable.

        Exposed so the bot can offer a top-up button pre-filled with exactly
        the gap, rather than sending the customer to an empty amount field.
        """
        return Money(max(0, amount.amount - self._balance))

    def recompute_balance(self) -> int:
        """Sum the ledger from scratch.

        Used by reconciliation jobs and tests to prove the stored balance and
        the history still agree. If this ever disagrees with ``balance``,
        trust this one.
        """
        return sum(entry.amount for entry in self._entries)

    # -- writing -----------------------------------------------------------

    def _append(
        self,
        *,
        entry_id: str,
        kind: TransactionKind,
        signed_amount: int,
        occurred_at: datetime,
        description_fa: str,
        reference: str | None,
        actor_id: int | None = None,
    ) -> LedgerEntry:
        new_balance = self._balance + signed_amount
        if new_balance < 0:
            raise InsufficientFunds(balance=self._balance, required=abs(signed_amount))

        entry = LedgerEntry(
            entry_id=entry_id,
            kind=kind,
            amount=signed_amount,
            balance_after=new_balance,
            occurred_at=occurred_at,
            description_fa=description_fa,
            reference=reference,
            actor_id=actor_id,
        )
        self._entries.append(entry)
        self._balance = new_balance

        event_type = WalletCredited if signed_amount > 0 else WalletDebited
        self.record(
            event_type(
                user_id=self.user_id,
                amount=abs(signed_amount),
                balance_after=new_balance,
                kind=str(kind),
                reference=reference,
            )
        )
        return entry

    def credit(
        self,
        amount: Money,
        *,
        entry_id: str,
        kind: TransactionKind,
        occurred_at: datetime,
        description_fa: str,
        reference: str | None = None,
        actor_id: int | None = None,
    ) -> LedgerEntry:
        """Add money.

        ``actor_id`` is optional because most credits are consequences of a
        rule (cashback, a referral, an overpayment) and have no author. It is
        recorded when there is one - an operator issuing a refund - because
        "who gave this customer money" is the first question asked when a
        ledger is audited.
        """
        if amount.amount <= 0:
            raise PaymentValidationError("A credit must be positive.")
        return self._append(
            entry_id=entry_id,
            kind=kind,
            signed_amount=amount.amount,
            occurred_at=occurred_at,
            description_fa=description_fa,
            reference=reference,
            actor_id=actor_id,
        )

    def debit(
        self,
        amount: Money,
        *,
        entry_id: str,
        kind: TransactionKind,
        occurred_at: datetime,
        description_fa: str,
        reference: str | None = None,
    ) -> LedgerEntry:
        """Take money. Raises rather than going negative."""
        if amount.amount <= 0:
            raise PaymentValidationError("A debit must be positive.")
        if not self.can_afford(amount):
            raise InsufficientFunds(balance=self._balance, required=amount.amount)
        return self._append(
            entry_id=entry_id,
            kind=kind,
            signed_amount=-amount.amount,
            occurred_at=occurred_at,
            description_fa=description_fa,
            reference=reference,
        )

    def top_up(
        self,
        amount: Money,
        *,
        entry_id: str,
        occurred_at: datetime,
        reference: str | None = None,
    ) -> LedgerEntry:
        """Credit from a settled top-up payment.

        Bounds are checked here as well as in the bot because this is the
        method an admin tool or a future gateway callback will also reach.
        """
        if amount.amount < MIN_TOPUP:
            raise PaymentValidationError(
                "The top-up amount is below the minimum.",
                amount=amount.amount,
                minimum=MIN_TOPUP,
            )
        if amount.amount > MAX_TOPUP:
            raise PaymentValidationError(
                "The top-up amount is above the maximum.",
                amount=amount.amount,
                maximum=MAX_TOPUP,
            )
        return self.credit(
            amount,
            entry_id=entry_id,
            kind=TransactionKind.TOPUP,
            occurred_at=occurred_at,
            description_fa="\u0634\u0627\u0631\u0698 \u06a9\u06cc\u0641 \u067e\u0648\u0644",
            reference=reference,
        )

    def adjust(
        self,
        signed_amount: int,
        *,
        entry_id: str,
        occurred_at: datetime,
        reason_fa: str,
        actor_id: int,
    ) -> LedgerEntry:
        """Manual operator correction, in either direction.

        The only wallet method that takes a signed integer instead of
        ``Money``, because it is the only one whose direction is a decision
        rather than a consequence. It always records the operator and always
        demands a reason: this is the entry that gets read out during a
        dispute.
        """
        if signed_amount == 0:
            raise PaymentValidationError("An adjustment cannot be for zero.")
        if len(reason_fa.strip()) < MIN_ADJUSTMENT_REASON:
            raise PaymentValidationError(
                "A wallet adjustment needs a written reason.",
                minimum=MIN_ADJUSTMENT_REASON,
            )
        return self._append(
            entry_id=entry_id,
            kind=TransactionKind.ADJUSTMENT,
            signed_amount=signed_amount,
            occurred_at=occurred_at,
            description_fa=reason_fa.strip(),
            reference=None,
            actor_id=actor_id,
        )

    # -- reporting ---------------------------------------------------------

    def total_of(self, kinds: Iterable[TransactionKind]) -> int:
        wanted = set(kinds)
        return sum(entry.amount for entry in self._entries if entry.kind in wanted)

    def history(
        self, *, kind: TransactionKind | None = None, newest_first: bool = True
    ) -> tuple[LedgerEntry, ...]:
        rows = [entry for entry in self._entries if kind is None or entry.kind is kind]
        rows.sort(key=lambda entry: entry.occurred_at, reverse=newest_first)
        return tuple(rows)


__all__ = [
    "MAX_TOPUP",
    "MIN_ADJUSTMENT_REASON",
    "MIN_TOPUP",
    "LedgerEntry",
    "Wallet",
]
