"""The bot ports whose data lives in the synchronous scope.

These adapters cross the sync/async boundary that `CLAUDE.md` forbids merging,
so the behaviour worth pinning is the translation either side of it: ledger
kinds, ticket states, and the fact that an unknown customer is answered with an
empty read model rather than an exception.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from geekvpn.application.bot import ports
from geekvpn.application.bot.read_models import TicketState as CardTicketState
from geekvpn.application.bot.read_models import TransactionKind as CardKind
from geekvpn.application.support.ticket_service import TicketSummary
from geekvpn.domain.payments.enums import TransactionKind
from geekvpn.domain.payments.wallet import LedgerEntry
from geekvpn.domain.support.enums import TicketCategory, TicketPriority, TicketState
from geekvpn.infrastructure.bot.sync_readers import (
    SyncBridge,
    SyncPreferencesCardStore,
    SyncTicketCardReader,
    SyncWalletCardReader,
    _to_ticket_card,
    _to_transaction,
)

NOW = datetime(2026, 8, 7, tzinfo=UTC)


class NoSuchUser:
    """A bridge for a customer that does not exist.

    Every adapter must answer without touching the synchronous scope at all -
    opening a session to look up nobody is wasted work on a hot path.
    """

    async def telegram_id(self, user_id: uuid.UUID) -> int | None:
        return None

    async def run(self, work: object) -> object:  # pragma: no cover - must not run
        raise AssertionError("The sync scope must not be opened for an unknown user.")


def test_the_sync_adapters_satisfy_the_ports_they_are_written_for() -> None:
    bridge = NoSuchUser()
    assert isinstance(SyncWalletCardReader(bridge), ports.WalletReader)  # type: ignore[arg-type]
    assert isinstance(SyncTicketCardReader(bridge), ports.TicketReader)  # type: ignore[arg-type]
    assert isinstance(SyncPreferencesCardStore(bridge), ports.PreferencesStore)  # type: ignore[arg-type]


async def test_an_unknown_customer_gets_empty_read_models_without_a_session() -> None:
    bridge = NoSuchUser()
    wallet = SyncWalletCardReader(bridge)  # type: ignore[arg-type]
    tickets = SyncTicketCardReader(bridge)  # type: ignore[arg-type]
    preferences = SyncPreferencesCardStore(bridge)  # type: ignore[arg-type]

    assert (await wallet.snapshot(uuid.uuid4())).balance == 0
    assert await wallet.transactions(uuid.uuid4()) == []
    assert await wallet.transaction_count(uuid.uuid4()) == 0
    assert await tickets.list_for_user(uuid.uuid4()) == []
    assert (await preferences.load(uuid.uuid4())).expiry is True


async def test_opening_a_ticket_for_an_unknown_customer_is_an_error_not_a_silent_noop() -> None:
    """Reads degrade to empty; a write must not pretend to have happened."""
    tickets = SyncTicketCardReader(NoSuchUser())  # type: ignore[arg-type]

    with pytest.raises(LookupError):
        await tickets.open_ticket(uuid.uuid4(), topic="t", message="m")


def entry(kind: TransactionKind, amount: int) -> LedgerEntry:
    return LedgerEntry(
        entry_id=str(uuid.uuid4()),
        kind=kind,
        amount=amount,
        balance_after=1000,
        occurred_at=NOW,
        description_fa="شارژ کیف پول",
    )


@pytest.mark.parametrize(
    ("domain_kind", "card_kind"),
    [
        (TransactionKind.TOPUP, CardKind.TOPUP),
        (TransactionKind.PURCHASE, CardKind.PURCHASE),
        (TransactionKind.REFERRAL_REWARD, CardKind.REFERRAL),
    ],
)
def test_ledger_kinds_map_onto_the_labels_the_customer_sees(
    domain_kind: TransactionKind, card_kind: CardKind
) -> None:
    assert _to_transaction(entry(domain_kind, 100)).kind is card_kind


def test_a_kind_with_no_customer_facing_label_is_shown_as_an_adjustment() -> None:
    """Dropping it would leave a balance change the customer cannot account for."""
    assert _to_transaction(entry(TransactionKind.OVERPAYMENT, 50)).kind is CardKind.ADJUSTMENT


def test_the_sign_of_a_ledger_entry_survives_translation() -> None:
    assert _to_transaction(entry(TransactionKind.PURCHASE, -250)).amount == -250


def summary(state: TicketState) -> TicketSummary:
    return TicketSummary(
        ticket_id=str(uuid.uuid4()),
        user_id=555,
        reference="TK-1",
        category=TicketCategory.OTHER,
        priority=TicketPriority.NORMAL,
        state=state,
        subject_fa="مشکل اتصال",
        assignee_id=None,
        created_at=NOW,
        updated_at=NOW,
        message_count=1,
        unread_for_agent=0,
        unread_for_customer=2,
        waiting_minutes=None,
    )


def test_waiting_on_the_customer_reads_as_waiting_not_as_open() -> None:
    """The domain calls it WAITING_USER; the card calls it WAITING. A missed
    mapping would silently show every waiting ticket as needing an agent."""
    assert _to_ticket_card(summary(TicketState.WAITING_USER)).state is CardTicketState.WAITING


def test_the_unread_count_shown_is_the_customer_side_one() -> None:
    assert _to_ticket_card(summary(TicketState.OPEN)).unread_count == 2


def test_the_bridge_exposes_what_the_adapters_need() -> None:
    assert hasattr(SyncBridge, "run")
    assert hasattr(SyncBridge, "telegram_id")
