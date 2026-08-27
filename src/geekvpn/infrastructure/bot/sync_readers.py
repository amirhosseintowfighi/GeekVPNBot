"""Bot ports whose data lives in the synchronous scope.

Wallets, tickets and notification preferences are owned by the synchronous
services (see ``di/sync_scope.py``), but the bot runs asynchronously and its
ports are ``async``. ``CLAUDE.md`` forbids mixing the two scopes in one
transaction, so these adapters do what the admin API already does: open a
**separate** synchronous session on a worker thread, finish the unit of work
there, and return a plain read model.

That means a bot update touching the wallet commits in two transactions, not
one. It is the correct trade: the alternative is a single transaction spanning
two engines, which is the thing the two-scope split exists to prevent.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import TypeVar

from starlette.concurrency import run_in_threadpool

from geekvpn.application.bot.read_models import (
    NotificationPreferences as PreferencesCard,
)
from geekvpn.application.bot.read_models import (
    TicketCard,
    TicketMessageCard,
    WalletSnapshot,
    WalletTransaction,
)
from geekvpn.application.bot.read_models import (
    TicketState as CardTicketState,
)
from geekvpn.application.bot.read_models import (
    TransactionKind as CardKind,
)
from geekvpn.application.support.ticket_service import (
    OpenTicketRequest,
    ReplyRequest,
    TicketSummary,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.rewards import tier_for_spend
from geekvpn.domain.payments.enums import TransactionKind
from geekvpn.domain.payments.wallet import LedgerEntry
from geekvpn.domain.support.enums import MessageKind, TicketCategory, TicketState
from geekvpn.infrastructure.di.container import Container
from geekvpn.infrastructure.di.sync_scope import SyncScope, build_sync_scope
from geekvpn.infrastructure.persistence.repositories.user import SqlAlchemyUserRepository

T = TypeVar("T")

#: `statement` slices in memory, so this is "give me the page that is the
#: whole history" rather than a real database limit.
_ALL_ENTRIES = 1_000_000

#: Ledger kinds the bot has no separate label for collapse onto ADJUSTMENT
#: rather than being dropped: a customer must be able to account for every
#: movement, even one whose name is only meaningful internally.
_CARD_KIND: dict[TransactionKind, CardKind] = {
    TransactionKind.TOPUP: CardKind.TOPUP,
    TransactionKind.PURCHASE: CardKind.PURCHASE,
    TransactionKind.REFUND: CardKind.REFUND,
    TransactionKind.CASHBACK: CardKind.CASHBACK,
    TransactionKind.REFERRAL_REWARD: CardKind.REFERRAL,
    TransactionKind.ADJUSTMENT: CardKind.ADJUSTMENT,
}

_CARD_TICKET_STATE: dict[TicketState, CardTicketState] = {
    TicketState.OPEN: CardTicketState.OPEN,
    TicketState.ANSWERED: CardTicketState.ANSWERED,
    TicketState.WAITING_USER: CardTicketState.WAITING,
    TicketState.CLOSED: CardTicketState.CLOSED,
}


class SyncBridge:
    """Runs one synchronous unit of work off the event loop.

    Shared by the adapters below so the commit/rollback discipline is written
    once. Mirrors ``presentation/api/admin_common.mutate_scope``.
    """

    def __init__(
        self,
        *,
        container: Container,
        users: SqlAlchemyUserRepository,
        reseller_id: uuid.UUID | None = None,
    ) -> None:
        self._container = container
        self._users = users
        # Carried across the async/sync boundary. Without it the synchronous
        # half - which is where payments live - would build a platform scope
        # for an update that arrived at a reseller's bot, and show their
        # customer our card.
        self._reseller_id = reseller_id

    async def telegram_id(self, user_id: uuid.UUID) -> int | None:
        user = await self._users.get(user_id)
        return user.telegram_id if user else None

    async def run(self, work: Callable[[SyncScope], T]) -> T:
        def _call() -> T:
            with self._container.sync_sessions() as session:
                scope = build_sync_scope(
                    self._container, session, reseller_id=self._reseller_id
                )
                try:
                    result = work(scope)
                    session.commit()
                    return result
                except Exception:
                    session.rollback()
                    raise

        return await run_in_threadpool(_call)


class SyncWalletCardReader:
    """Implements ``WalletReader``."""

    def __init__(self, bridge: SyncBridge) -> None:
        self._bridge = bridge

    async def snapshot(self, user_id: uuid.UUID) -> WalletSnapshot:
        telegram_id = await self._bridge.telegram_id(user_id)
        if telegram_id is None:
            return WalletSnapshot()

        def work(scope: SyncScope) -> WalletSnapshot:
            # ponytail: lifetime spend is summed from the full ledger, which
            # `statement` already materialises whatever limit it is given. Fine
            # at a few hundred entries per customer; move to a stored total on
            # the wallet aggregate if a heavy user makes this show up.
            statement = scope.wallet.statement(telegram_id, limit=_ALL_ENTRIES)
            spend = sum(-e.amount for e in statement.entries if e.amount < 0)
            return WalletSnapshot(
                balance=statement.balance,
                lifetime_spend=spend,
                tier=tier_for_spend(Money(spend)),
            )

        return await self._bridge.run(work)

    async def transactions(
        self, user_id: uuid.UUID, *, limit: int = 8, offset: int = 0
    ) -> list[WalletTransaction]:
        telegram_id = await self._bridge.telegram_id(user_id)
        if telegram_id is None:
            return []

        def work(scope: SyncScope) -> list[WalletTransaction]:
            statement = scope.wallet.statement(telegram_id, limit=limit, offset=offset)
            return [_to_transaction(entry) for entry in statement.entries]

        return await self._bridge.run(work)

    async def transaction_count(self, user_id: uuid.UUID) -> int:
        telegram_id = await self._bridge.telegram_id(user_id)
        if telegram_id is None:
            return 0

        def work(scope: SyncScope) -> int:
            return scope.wallet.statement(telegram_id, limit=0).total

        return await self._bridge.run(work)


class SyncTicketCardReader:
    """Implements ``TicketReader``."""

    def __init__(self, bridge: SyncBridge) -> None:
        self._bridge = bridge

    async def open_ticket(self, user_id: uuid.UUID, *, topic: str, message: str) -> TicketCard:
        telegram_id = await self._bridge.telegram_id(user_id)
        if telegram_id is None:
            raise LookupError(f"No user {user_id}.")

        category, subject = _categorise(topic)

        def work(scope: SyncScope) -> TicketCard:
            summary = scope.support.open_ticket(
                OpenTicketRequest(
                    user_id=telegram_id,
                    subject_fa=subject,
                    category=category,
                    first_message_fa=message,
                )
            )
            return _to_ticket_card(summary)

        return await self._bridge.run(work)

    async def thread(
        self, user_id: uuid.UUID, *, ticket_id: uuid.UUID
    ) -> list[TicketMessageCard]:
        """The conversation, oldest first.

        Ownership is checked here and not assumed: a ticket id reaches this
        method through a Telegram callback, which anyone can craft.
        """
        telegram_id = await self._bridge.telegram_id(user_id)
        if telegram_id is None:
            return []

        # Stored ids are hex without dashes. `str(UUID)` puts them in, and the
        # lookup then finds nothing - the same trap the payment ids fell into.
        # Converting here rather than at every call site keeps one spelling.
        stored = ticket_id.hex

        def work(scope: SyncScope) -> list[TicketMessageCard]:
            if scope.support.get_ticket(stored).user_id != telegram_id:
                return []
            return [
                TicketMessageCard(
                    message_id=_as_uuid(message.message_id),
                    from_support=message.kind is MessageKind.SUPPORT,
                    body_fa=message.body_fa,
                    created_at=message.created_at,
                )
                # Internal notes are excluded by default and must stay that
                # way: they are written for colleagues, about the customer.
                for message in scope.support.get_messages(stored)
            ]

        return await self._bridge.run(work)

    async def reply(
        self, user_id: uuid.UUID, *, ticket_id: uuid.UUID, message: str
    ) -> TicketCard:
        telegram_id = await self._bridge.telegram_id(user_id)
        if telegram_id is None:
            raise LookupError(f"No user {user_id}.")

        stored = ticket_id.hex

        def work(scope: SyncScope) -> TicketCard:
            summary = scope.support.get_ticket(stored)
            if summary.user_id != telegram_id:
                raise LookupError("Not this customer's ticket.")
            scope.support.customer_reply(
                ReplyRequest(ticket_id=stored, body_fa=message, author_id=telegram_id)
            )
            return _to_ticket_card(scope.support.get_ticket(stored))

        return await self._bridge.run(work)

    async def find_by_reference(
        self, user_id: uuid.UUID, *, reference: str
    ) -> TicketCard | None:
        """Matched against this customer's own tickets, never searched globally.

        The reference is printed in every message the bot sends about a ticket,
        so it arrives back typed or quoted by whoever is replying - which is
        exactly why it is only ever resolved within their own list.
        """
        wanted = reference.strip().upper()
        return next(
            (card for card in await self.list_for_user(user_id) if card.reference.upper() == wanted),
            None,
        )

    async def list_for_user(self, user_id: uuid.UUID) -> list[TicketCard]:
        telegram_id = await self._bridge.telegram_id(user_id)
        if telegram_id is None:
            return []

        def work(scope: SyncScope) -> list[TicketCard]:
            return [
                _to_ticket_card(summary) for summary in scope.support.list_for_user(telegram_id)
            ]

        return await self._bridge.run(work)


class SyncPreferencesCardStore:
    """Implements ``PreferencesStore``.

    The domain model carries quiet hours and per-channel switches that the bot
    surfaces as one toggle, so this narrows rather than round-trips: only the
    four category flags and the quiet-hours switch cross the boundary.
    """

    def __init__(self, bridge: SyncBridge) -> None:
        self._bridge = bridge

    async def load(self, user_id: uuid.UUID) -> PreferencesCard:
        telegram_id = await self._bridge.telegram_id(user_id)
        if telegram_id is None:
            return PreferencesCard()

        def work(scope: SyncScope) -> PreferencesCard:
            stored = scope.preferences.load(telegram_id)
            return PreferencesCard(
                expiry=stored.expiry,
                traffic=stored.traffic,
                promos=stored.promos,
                news=stored.news,
                quiet_hours=stored.quiet.enabled,
            )

        return await self._bridge.run(work)

    async def save(self, user_id: uuid.UUID, preferences: PreferencesCard) -> PreferencesCard:
        telegram_id = await self._bridge.telegram_id(user_id)
        if telegram_id is None:
            return preferences

        def work(scope: SyncScope) -> PreferencesCard:
            stored = scope.preferences.load(telegram_id)
            scope.preferences.save(
                telegram_id,
                replace(
                    stored,
                    expiry=preferences.expiry,
                    traffic=preferences.traffic,
                    promos=preferences.promos,
                    news=preferences.news,
                    quiet=replace(stored.quiet, enabled=preferences.quiet_hours),
                ),
            )
            return preferences

        return await self._bridge.run(work)


def _to_transaction(entry: LedgerEntry) -> WalletTransaction:
    return WalletTransaction(
        transaction_id=_as_uuid(entry.entry_id),
        kind=_CARD_KIND.get(entry.kind, CardKind.ADJUSTMENT),
        amount=entry.amount,
        created_at=entry.occurred_at,
        description_fa=entry.description_fa,
        balance_after=entry.balance_after,
    )


def _to_ticket_card(summary: TicketSummary) -> TicketCard:
    return TicketCard(
        ticket_id=_as_uuid(summary.ticket_id),
        reference=summary.reference,
        topic_fa=summary.subject_fa,
        state=_CARD_TICKET_STATE.get(summary.state, CardTicketState.OPEN),
        created_at=summary.created_at,
        unread_count=summary.unread_for_customer,
        last_reply_at=summary.updated_at,
    )


def _as_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        return uuid.UUID(int=0)


__all__ = [
    "SyncBridge",
    "SyncPreferencesCardStore",
    "SyncTicketCardReader",
    "SyncWalletCardReader",
]


def _categorise(topic: str) -> tuple[TicketCategory, str]:
    """Turn whatever the front-end sent into a category and a Persian subject.

    The bot sends a category key - "connection" - and it was being written
    straight into `subject_fa`, so an agent's queue read "connection" in Latin
    script while `category` stayed OTHER for every ticket ever opened, which is
    the field the queue filters on.

    The Mini App sends free text instead, which matches no category and is
    already the subject. Both arrive here, so both are handled here.
    """
    try:
        category = TicketCategory(topic)
    except ValueError:
        return TicketCategory.OTHER, topic
    return category, category.label_fa()
