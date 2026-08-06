"""Integration tests for TicketService."""

from __future__ import annotations

import pytest

from geekvpn.application.support.ticket_service import (
    NoteRequest,
    ReplyRequest,
)
from geekvpn.domain.support.enums import MessageKind, TicketCategory, TicketPriority, TicketState
from geekvpn.domain.support.errors import MessageTooShort, TicketNotFound
from geekvpn.domain.support.events import (
    TicketClosed as TicketClosedEvent,
)
from geekvpn.domain.support.events import (
    TicketOpened,
)
from tests.unit.support.fakes import AGENT_ID, USER_ID
from tests.unit.support.world import World


def test_open_ticket_creates_a_summary_in_open_state():
    w = World()
    summary = w.open()
    assert summary.state is TicketState.OPEN
    assert summary.user_id == USER_ID


def test_reference_follows_the_sup_format():
    w = World()
    summary = w.open()
    assert summary.reference.startswith("SUP-")
    parts = summary.reference.split("-")
    assert len(parts) == 3
    assert parts[2].isdigit()


def test_sequential_tickets_get_distinct_references():
    w = World()
    first = w.open()
    second = w.open()
    assert first.reference != second.reference
    seq1 = int(first.reference.split("-")[2])
    seq2 = int(second.reference.split("-")[2])
    assert seq2 == seq1 + 1


def test_opening_notifies_the_agent():
    w = World()
    w.open()
    assert len(w.notifier.new_ticket_calls) == 1


def test_opening_emits_ticket_opened_event():
    w = World()
    w.open()
    opened = w.events.of_type(TicketOpened)
    assert len(opened) == 1
    assert opened[0].user_id == USER_ID


def test_agent_reply_moves_ticket_to_waiting_user():
    w = World()
    summary = w.open()
    w.tickets.agent_reply(
        ReplyRequest(
            ticket_id=summary.ticket_id,
            body_fa="\u0645\u0634\u06a9\u0644 \u0628\u0631\u0631\u0633\u06cc \u0634\u062f \u0644\u0637\u0641\u0627\u064b \u067e\u0627\u0633\u062e \u062f\u0647\u06cc\u062f",
            author_id=AGENT_ID,
        )
    )
    updated = w.tickets.get_ticket(summary.ticket_id)
    assert updated.state is TicketState.WAITING_USER


def test_agent_reply_notifies_the_customer():
    w = World()
    summary = w.open()
    w.tickets.agent_reply(
        ReplyRequest(
            ticket_id=summary.ticket_id,
            body_fa="\u067e\u0627\u0633\u062e \u062a\u06cc\u0645 \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc",
            author_id=AGENT_ID,
        )
    )
    assert len(w.notifier.customer_reply_calls) == 1


def test_customer_reply_after_agent_reopens_ticket():
    w = World()
    summary = w.open()
    w.tickets.agent_reply(
        ReplyRequest(
            ticket_id=summary.ticket_id,
            body_fa="\u0644\u0637\u0641\u0627\u064b \u0627\u0637\u0644\u0627\u0639\u0627\u062a \u0628\u06cc\u0634\u062a\u0631\u06cc \u0628\u062f\u0647\u06cc\u062f",
            author_id=AGENT_ID,
        )
    )
    w.tickets.customer_reply(
        ReplyRequest(
            ticket_id=summary.ticket_id,
            body_fa="\u062f\u0631 \u062d\u0627\u0644 \u062d\u0627\u0636\u0631 \u0647\u0645\u0627\u0646 \u0645\u0634\u06a9\u0644 \u0648\u062c\u0648\u062f \u062f\u0627\u0631\u062f",
            author_id=USER_ID,
        )
    )
    updated = w.tickets.get_ticket(summary.ticket_id)
    assert updated.state is TicketState.OPEN


def test_internal_note_does_not_appear_in_customer_history():
    w = World()
    summary = w.open()
    w.tickets.add_note(
        NoteRequest(
            ticket_id=summary.ticket_id,
            body_fa="\u06cc\u0627\u062f\u062f\u0627\u0634\u062a \u062e\u0635\u0648\u0635\u06cc",
            author_id=AGENT_ID,
        )
    )
    customer_view = w.tickets.get_messages(summary.ticket_id, include_internal=False)
    assert all(m.kind is not MessageKind.NOTE for m in customer_view)


def test_internal_note_appears_for_agents():
    w = World()
    summary = w.open()
    w.tickets.add_note(
        NoteRequest(
            ticket_id=summary.ticket_id,
            body_fa="\u06cc\u0627\u062f\u062f\u0627\u0634\u062a \u062e\u0635\u0648\u0635\u06cc",
            author_id=AGENT_ID,
        )
    )
    agent_view = w.tickets.get_messages(summary.ticket_id, include_internal=True)
    assert any(m.kind is MessageKind.NOTE for m in agent_view)


def test_closing_by_agent_notifies_customer():
    w = World()
    summary = w.open()
    w.tickets.close_ticket(summary.ticket_id, actor_id=AGENT_ID, closed_by_agent=True)
    assert len(w.notifier.customer_closed_calls) == 1


def test_closing_emits_event():
    w = World()
    summary = w.open()
    w.tickets.close_ticket(summary.ticket_id, actor_id=AGENT_ID, closed_by_agent=True)
    closed = w.events.of_type(TicketClosedEvent)
    assert len(closed) == 1
    assert closed[0].closed_by_agent is True


def test_closing_twice_does_not_notify_twice():
    w = World()
    summary = w.open()
    w.tickets.close_ticket(summary.ticket_id, actor_id=AGENT_ID, closed_by_agent=True)
    w.tickets.close_ticket(summary.ticket_id, actor_id=AGENT_ID, closed_by_agent=True)
    assert len(w.notifier.customer_closed_calls) == 1


def test_priority_escalation_is_reflected_in_summary():
    w = World()
    summary = w.open(priority=TicketPriority.NORMAL)
    escalated = w.tickets.change_priority(
        summary.ticket_id, TicketPriority.URGENT, actor_id=AGENT_ID
    )
    assert escalated.priority is TicketPriority.URGENT


def test_category_change_is_reflected_in_summary():
    w = World()
    summary = w.open(category=TicketCategory.CONNECTION)
    updated = w.tickets.change_category(
        summary.ticket_id, TicketCategory.PAYMENT, actor_id=AGENT_ID
    )
    assert updated.category is TicketCategory.PAYMENT


def test_assign_sets_assignee():
    w = World()
    summary = w.open()
    assigned = w.tickets.assign_ticket(summary.ticket_id, AGENT_ID, actor_id=AGENT_ID)
    assert assigned.assignee_id == AGENT_ID


def test_unassign_clears_assignee():
    w = World()
    summary = w.open()
    w.tickets.assign_ticket(summary.ticket_id, AGENT_ID, actor_id=AGENT_ID)
    unassigned = w.tickets.assign_ticket(summary.ticket_id, None, actor_id=AGENT_ID)
    assert unassigned.assignee_id is None


def test_list_for_user_returns_only_their_tickets():
    w = World()
    w.open(user_id=USER_ID)
    w.open(user_id=USER_ID)
    w.open(user_id=9999)
    results = w.tickets.list_for_user(USER_ID)
    assert len(results) == 2
    assert all(r.user_id == USER_ID for r in results)


def test_queue_returns_only_open_tickets():
    w = World()
    w.open()
    s2 = w.open()
    w.tickets.close_ticket(s2.ticket_id, actor_id=AGENT_ID, closed_by_agent=True)
    queue = w.tickets.queue()
    assert all(s.state.awaits_agent() for s in queue)
    assert len(queue) == 1


def test_mark_read_clears_unread_count():
    w = World()
    summary = w.open()
    assert summary.unread_for_agent == 1
    changed = w.tickets.mark_read(summary.ticket_id, viewer_is_agent=True)
    assert changed == 1
    refreshed = w.tickets.get_ticket(summary.ticket_id)
    assert refreshed.unread_for_agent == 0


def test_short_message_raises_on_customer_reply():
    w = World()
    summary = w.open()
    with pytest.raises(MessageTooShort):
        w.tickets.customer_reply(
            ReplyRequest(
                ticket_id=summary.ticket_id,
                body_fa="hi",
                author_id=USER_ID,
            )
        )


def test_get_nonexistent_ticket_raises():
    w = World()
    with pytest.raises(TicketNotFound):
        w.tickets.get_ticket("no-such-ticket")
