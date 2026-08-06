"""Wallet use cases: reading balances and moving money by hand.

Deliberately thin. Every rule about whether money *may* move lives in the
``Wallet`` aggregate; what lives here is the loading, locking and saving
around it.

Note what is **not** here. Purchases debit the wallet inside
``CheckoutService``, and refunds credit it inside ``RefundService``, because
in both cases the wallet movement and the payment change must be one atomic
step. Exposing a public ``debit`` for checkout to call would invite a caller
to take the money and then fail to record why - the worst possible failure in
a payment system, because it is invisible until the customer complains.

What remains is the operator surface (adjustments) and the customer surface
(balance, statement, integrity check).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from geekvpn.application.payments.ports import (
    Clock,
    EventPublisher,
    IdGenerator,
    PaymentAuditLog,
    PaymentNotifier,
    WalletRepository,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import TransactionKind
from geekvpn.domain.payments.wallet import LedgerEntry

TOPUP_PRESETS: tuple[int, ...] = (200_000, 500_000, 1_000_000, 2_000_000)
"""The buttons offered before "another amount".

Shared with the bot and the Mini App so the ladder is identical everywhere.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class Statement:
    """A page of history together with the balance it belongs to.

    One object because every screen that shows history also shows the balance,
    and fetching them separately invites the two to disagree across a
    concurrent write.
    """

    balance: int
    entries: tuple[LedgerEntry, ...]
    total: int
    page_size: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.entries) < self.total

    @property
    def is_empty(self) -> bool:
        return not self.entries and self.offset == 0


class WalletService:
    """Balances, statements and operator adjustments."""

    __slots__ = ("_audit", "_clock", "_events", "_ids", "_notifier", "_wallets")

    def __init__(
        self,
        *,
        wallets: WalletRepository,
        clock: Clock,
        ids: IdGenerator,
        events: EventPublisher,
        audit: PaymentAuditLog,
        notifier: PaymentNotifier | None = None,
    ) -> None:
        self._wallets = wallets
        self._clock = clock
        self._ids = ids
        self._events = events
        self._audit = audit
        self._notifier = notifier

    # -- reading -----------------------------------------------------------

    def balance(self, user_id: int) -> Money:
        return self._wallets.get_or_create(user_id).balance

    def can_afford(self, user_id: int, amount: Money) -> bool:
        return self._wallets.get_or_create(user_id).can_afford(amount)

    def shortfall_for(self, user_id: int, amount: Money) -> Money:
        """How much is missing, so the bot can pre-fill the top-up amount.

        Offering "top up" without naming the gap makes the customer do
        arithmetic in order to buy something, which is a good way to lose a
        sale that was already agreed.
        """
        return self._wallets.get_or_create(user_id).shortfall_for(amount)

    def statement(
        self,
        user_id: int,
        *,
        limit: int = 10,
        offset: int = 0,
        kind: TransactionKind | None = None,
    ) -> Statement:
        """Transaction history, newest first.

        The balance is taken from the aggregate rather than from the first
        row's ``balance_after``. On a filtered view the newest *matching*
        entry is not the newest entry, and printing its witness as "your
        balance" would be quietly, confidently wrong.
        """
        wallet = self._wallets.get_or_create(user_id)
        rows: Sequence[LedgerEntry] = wallet.history(kind=kind)
        page = rows[offset : offset + limit]
        return Statement(
            balance=wallet.balance.amount,
            entries=tuple(page),
            total=len(rows),
            page_size=limit,
            offset=offset,
        )

    def verify_integrity(self, user_id: int) -> bool:
        """Replay the ledger and compare it against the recorded running total.

        Support runs this before arguing with a customer about a balance. A
        false result is not a customer error - it means a stored
        ``balance_after`` was written by something that is not this code.
        """
        wallet = self._wallets.get_or_create(user_id)
        replayed = wallet.recompute_balance()
        if replayed != wallet.balance.amount:
            return False
        entries = wallet.entries
        return not entries or entries[-1].balance_after == replayed

    # -- operator surface --------------------------------------------------

    def adjust(
        self, *, user_id: int, signed_amount: int, actor_id: int, reason_fa: str
    ) -> LedgerEntry:
        """An operator moves money by hand, in either direction.

        The only signed-amount entry point in the system and the only one that
        names a human. Everything else is a typed movement whose direction is
        a consequence rather than a decision.

        The aggregate enforces the written reason. It is enforced there and
        not here so that an admin script reaching the aggregate directly still
        cannot produce an unexplained entry.
        """
        wallet = self._wallets.get_or_create(user_id)
        entry = wallet.adjust(
            signed_amount,
            entry_id=self._ids.new_id(),
            occurred_at=self._clock.now(),
            reason_fa=reason_fa,
            actor_id=actor_id,
        )
        self._wallets.save(wallet)
        self._publish(wallet)
        self._audit.record(
            action="wallet.adjust",
            actor_id=actor_id,
            payment_id=entry.entry_id,
            details={
                "user_id": user_id,
                "amount": signed_amount,
                "balance_after": entry.balance_after,
                "reason_fa": entry.description_fa,
            },
        )

        if self._notifier is not None and signed_amount > 0:
            # Customers hear when money appears. They are not pestered when a
            # correction removes money they never knew they had.
            self._notifier.wallet_credited(
                user_id,
                amount=signed_amount,
                balance=entry.balance_after,
                reason_fa=entry.description_fa,
            )
        return entry

    def credit_reward(
        self,
        *,
        user_id: int,
        amount: Money,
        kind: TransactionKind,
        description_fa: str,
        reference: str | None = None,
    ) -> LedgerEntry:
        """Cashback and referral rewards.

        Separate from ``adjust`` because these are earned by a rule rather
        than decided by a person, so there is no actor to record and no reason
        to demand - the description is generated from the rule that fired.
        """
        wallet = self._wallets.get_or_create(user_id)
        entry = wallet.credit(
            amount,
            entry_id=self._ids.new_id(),
            kind=kind,
            occurred_at=self._clock.now(),
            description_fa=description_fa,
            reference=reference,
        )
        self._wallets.save(wallet)
        self._publish(wallet)

        if self._notifier is not None:
            self._notifier.wallet_credited(
                user_id,
                amount=amount.amount,
                balance=entry.balance_after,
                reason_fa=description_fa,
            )
        return entry

    # -- internals ---------------------------------------------------------

    def _publish(self, *aggregates: object) -> None:
        collected: list[object] = []
        for aggregate in aggregates:
            collect = getattr(aggregate, "collect_events", None)
            if collect is not None:
                collected.extend(collect())
        if collected:
            self._events.publish_all(collected)


__all__ = ["TOPUP_PRESETS", "Statement", "WalletService"]
