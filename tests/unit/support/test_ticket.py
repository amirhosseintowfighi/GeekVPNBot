"""Unit tests for the Ticket aggregate."""

from __future__ import annotations

from datetime import timedelta

import pytest

from geekvpn.domain.support.enums import (
    MessageKind,
    TicketCategory,
    TicketPriority,
    TicketState,
)
from geekvpn.domain.support.errors import (
    InvalidAttachment,
    MessageTooShort,
    TicketClosed,
    TooManyAttachments,
)
from geekvpn.domain.support.events import TicketOpened, TicketPriorityChanged, TicketReplied
from geekvpn.domain.support.ticket import Attachment, Ticket
from tests.unit.support.fakes import AGENT_ID, EPOCH, USER_ID, FakeIds


def _open_ticket(**kwargs) -> Ticket:
    ids = FakeIds()
    defaults = {
        "user_id": USER_ID,
        "reference": "SUP-1405-000001",
        "category": TicketCategory.CONNECTION,
        "priority": TicketPriority.NORMAL,
        "subject_fa": "\u0645\u0634\u06a9\u0644 \u0627\u062a\u0635\u0627\u0644",
        "first_message_fa": "\u0633\u0631\u0648\u06cc\u0633 \u0648\u0635\u0644 \u0646\u0645\u06cc\u200c\u0634\u0648\u062f \u0644\u0637\u0641\u0627\u064b",
        "first_message_id": ids.new_id(),
        "now": EPOCH,
    }
    defaults.update(kwargs)
    return Ticket.open(ids.new_id(), **defaults)


def test_opening_a_ticket_puts_it_in_the_open_state():
    ticket = _open_ticket()
    assert ticket.state is TicketState.OPEN


def test_opening_records_the_first_message():
    ticket = _open_ticket()
    assert len(ticket.messages) == 1
    assert ticket.messages[0].kind is MessageKind.CUSTOMER


def test_opening_emits_ticket_opened_event():
    ticket = _open_ticket()
    events = ticket.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], TicketOpened)
    assert events[0].user_id == USER_ID


def test_first_message_too_short_raises():
    with pytest.raises(MessageTooShort):
        _open_ticket(first_message_fa="hi")


def test_agent_reply_moves_state_to_waiting_user():
    ticket = _open_ticket()
    ticket.collect_events()
    ids = FakeIds()
    ticket.reply_by_agent(
        message_id=ids.new_id(),
        body_fa="\u0645\u0634\u06a9\u0644 \u0634\u0645\u0627 \u0628\u0631\u0631\u0633\u06cc \u0634\u062f \u0644\u0637\u0641\u0627\u064b \u0627\u0637\u0644\u0627\u0639\u0627\u062a \u0628\u06cc\u0634\u062a\u0631\u06cc \u0628\u062f\u0647\u06cc\u062f",
        author_id=AGENT_ID,
        now=EPOCH,
    )
    assert ticket.state is TicketState.WAITING_USER


def test_agent_reply_emits_ticket_replied_event():
    ticket = _open_ticket()
    ticket.collect_events()
    ids = FakeIds()
    ticket.reply_by_agent(
        message_id=ids.new_id(),
        body_fa="\u067e\u0627\u0633\u062e \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc \u0628\u0631\u0627\u06cc \u06a9\u0627\u0631\u0628\u0631 \u0639\u0632\u06cc\u0632",
        author_id=AGENT_ID,
        now=EPOCH,
    )
    events = ticket.collect_events()
    assert any(isinstance(e, TicketReplied) and e.kind is MessageKind.SUPPORT for e in events)


def test_customer_reply_moves_state_back_to_open():
    ticket = _open_ticket()
    ids = FakeIds()
    ticket.reply_by_agent(
        message_id=ids.new_id(),
        body_fa="\u0644\u0637\u0641\u0627\u064b \u0627\u0637\u0644\u0627\u0639\u0627\u062a \u0628\u06cc\u0634\u062a\u0631\u06cc \u0628\u062f\u0647\u06cc\u062f",
        author_id=AGENT_ID,
        now=EPOCH,
    )
    assert ticket.state is TicketState.WAITING_USER
    ticket.collect_events()
    ticket.reply_by_customer(
        message_id=ids.new_id(),
        body_fa="\u062f\u0631 \u062d\u0627\u0644 \u062d\u0627\u0636\u0631 \u0647\u0645\u0627\u0646 \u0645\u0634\u06a9\u0644 \u0648\u062c\u0648\u062f \u062f\u0627\u0631\u062f",
        author_id=USER_ID,
        now=EPOCH,
    )
    assert ticket.state is TicketState.OPEN


def test_internal_note_does_not_change_state():
    ticket = _open_ticket()
    ids = FakeIds()
    ticket.reply_by_agent(
        message_id=ids.new_id(),
        body_fa="\u0644\u0637\u0641\u0627\u064b \u0627\u0637\u0644\u0627\u0639\u0627\u062a \u0628\u06cc\u0634\u062a\u0631\u06cc \u0628\u062f\u0647\u06cc\u062f",
        author_id=AGENT_ID,
        now=EPOCH,
    )
    assert ticket.state is TicketState.WAITING_USER
    ticket.collect_events()
    ticket.add_internal_note(
        message_id=ids.new_id(),
        body_fa="\u06a9\u0627\u0631\u0628\u0631 \u06cc\u06a9 \u0628\u0627\u0631 \u0642\u0628\u0644\u0627\u064b \u0647\u0645 \u062a\u06cc\u06a9\u062a \u062f\u0627\u0634\u062a",
        author_id=AGENT_ID,
        now=EPOCH,
    )
    assert ticket.state is TicketState.WAITING_USER
    assert not ticket.collect_events()  # no event for internal notes


def test_internal_note_is_not_in_customer_messages():
    ticket = _open_ticket()
    ids = FakeIds()
    ticket.add_internal_note(
        message_id=ids.new_id(),
        body_fa="\u06cc\u0627\u062f\u062f\u0627\u0634\u062a \u062e\u0635\u0648\u0635\u06cc \u062a\u06cc\u0645 \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc",
        author_id=AGENT_ID,
        now=EPOCH,
    )
    customer_msgs = ticket.customer_messages()
    assert all(m.kind is not MessageKind.NOTE for m in customer_msgs)


def test_closing_a_ticket_marks_it_terminal():
    ticket = _open_ticket()
    ticket.close(closed_by_agent=True, now=EPOCH)
    assert ticket.state.is_terminal()


def test_agent_cannot_reply_to_a_closed_ticket():
    ticket = _open_ticket()
    ticket.close(closed_by_agent=True, now=EPOCH)
    ids = FakeIds()
    with pytest.raises(TicketClosed):
        ticket.reply_by_agent(
            message_id=ids.new_id(),
            body_fa="\u0628\u0639\u062f \u0627\u0632 \u0628\u0633\u062a\u0647 \u0634\u062f\u0646 \u067e\u06cc\u0627\u0645",
            author_id=AGENT_ID,
            now=EPOCH,
        )


def test_customer_replying_to_a_closed_ticket_reopens_it():
    ticket = _open_ticket()
    ticket.close(closed_by_agent=True, now=EPOCH)
    ticket.collect_events()
    ids = FakeIds()
    ticket.reply_by_customer(
        message_id=ids.new_id(),
        body_fa="\u0645\u0634\u06a9\u0644 \u062f\u0648\u0628\u0627\u0631\u0647 \u0628\u0631\u06af\u0634\u062a",
        author_id=USER_ID,
        now=EPOCH,
    )
    assert ticket.state is TicketState.OPEN


def test_closing_twice_is_idempotent():
    ticket = _open_ticket()
    ticket.close(closed_by_agent=True, now=EPOCH)
    ticket.collect_events()
    ticket.close(closed_by_agent=True, now=EPOCH)
    events = ticket.collect_events()
    assert events == []  # second close produces no additional event


def test_priority_change_appends_a_status_message():
    ticket = _open_ticket()
    ids = FakeIds()
    before = len(ticket.messages)
    ticket.change_priority(
        TicketPriority.URGENT, actor_id=AGENT_ID, note_id=ids.new_id(), now=EPOCH
    )
    assert len(ticket.messages) == before + 1
    assert ticket.messages[-1].kind is MessageKind.STATUS_CHANGE
    assert ticket.priority is TicketPriority.URGENT


def test_priority_change_emits_event():
    ticket = _open_ticket()
    ticket.collect_events()
    ids = FakeIds()
    ticket.change_priority(TicketPriority.HIGH, actor_id=AGENT_ID, note_id=ids.new_id(), now=EPOCH)
    events = ticket.collect_events()
    assert any(isinstance(e, TicketPriorityChanged) for e in events)


def test_same_priority_change_is_a_noop():
    ticket = _open_ticket()
    ticket.collect_events()
    before = len(ticket.messages)
    ids = FakeIds()
    ticket.change_priority(
        TicketPriority.NORMAL, actor_id=AGENT_ID, note_id=ids.new_id(), now=EPOCH
    )
    assert len(ticket.messages) == before
    assert not ticket.collect_events()


def test_category_change_appends_a_status_message():
    ticket = _open_ticket()
    ids = FakeIds()
    ticket.change_category(
        TicketCategory.PAYMENT, actor_id=AGENT_ID, note_id=ids.new_id(), now=EPOCH
    )
    assert ticket.messages[-1].kind is MessageKind.STATUS_CHANGE
    assert ticket.category is TicketCategory.PAYMENT


def test_valid_attachment_is_accepted():
    ids = FakeIds()
    att = Attachment(file_id="tg-abc", mime_type="image/jpeg")
    ticket = _open_ticket(first_message_id=ids.new_id(), attachments=[att])
    assert ticket.messages[0].attachments[0].file_id == "tg-abc"


def test_invalid_mime_type_raises():
    with pytest.raises(InvalidAttachment):
        Attachment(file_id="tg-exe", mime_type="application/x-executable")


def test_too_many_attachments_raises():
    atts = [Attachment(file_id=f"tg-{i}", mime_type="image/jpeg") for i in range(6)]
    with pytest.raises(TooManyAttachments):
        _open_ticket(attachments=atts)


def test_unread_count_for_agent_increments_with_customer_messages():
    ticket = _open_ticket()
    assert ticket.unread_count_for_agent() == 1  # first message


def test_mark_messages_read_clears_unread_for_agent():
    ticket = _open_ticket()
    changed = ticket.mark_messages_read(viewer_is_agent=True, now=EPOCH)
    assert changed == 1
    assert ticket.unread_count_for_agent() == 0


def test_waiting_minutes_reflects_age_of_oldest_unread_customer_message():
    ticket = _open_ticket()
    later = EPOCH + timedelta(hours=2)
    minutes = ticket.waiting_minutes(later)
    assert minutes == 120


def test_waiting_minutes_is_none_when_no_unread_customer_messages():
    ticket = _open_ticket()
    ticket.mark_messages_read(viewer_is_agent=True, now=EPOCH)
    assert ticket.waiting_minutes(EPOCH) is None
