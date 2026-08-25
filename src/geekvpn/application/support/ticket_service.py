"""Ticket service — all use cases that mutate a ticket.

One method per use case. The service owns the transaction boundary: it loads,
mutates, saves, publishes events, and fires notifications. No method returns
raw domain objects to the caller; callers get only what they need.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from geekvpn.application.support.ports import (
    Clock,
    EventPublisher,
    IdGenerator,
    SupportNotifier,
    TemplateRepository,
    TicketRepository,
)
from geekvpn.domain.support.enums import (
    MessageKind,
    TicketCategory,
    TicketPriority,
    TicketState,
)
from geekvpn.domain.support.errors import TemplateNotFound
from geekvpn.domain.support.ticket import (
    Attachment,
    Message,
    Ticket,
    format_ticket_reference,
)


def _gregorian_to_jalali_year(year: int) -> int:
    """Approximate Jalali year for grouping. Good enough for ticket numbers.

    Minus, not plus. The comment underneath always said 2026 -> 1405 and the
    arithmetic said 2647, so the first references this platform issued read
    `SUP-2647-000003`. Nobody noticed for as long as nobody could open a ticket
    at all.

    Off by a few weeks either side of Nowruz, which is deliberate: this groups
    reference numbers, and a ticket filed on the 19th of March landing in last
    year's run is not worth a calendar conversion to prevent.
    """
    return year - 621


@dataclass(frozen=True, slots=True)
class OpenTicketRequest:
    user_id: int
    subject_fa: str
    first_message_fa: str
    category: TicketCategory = TicketCategory.OTHER
    priority: TicketPriority = TicketPriority.NORMAL
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True, slots=True)
class ReplyRequest:
    ticket_id: str
    body_fa: str
    author_id: int
    attachments: tuple[Attachment, ...] = ()
    template_id: str | None = None


@dataclass(frozen=True, slots=True)
class NoteRequest:
    ticket_id: str
    body_fa: str
    author_id: int
    attachments: tuple[Attachment, ...] = ()


@dataclass(frozen=True, slots=True)
class TicketSummary:
    """Read-model returned to callers. The aggregate stays inside the service."""

    ticket_id: str
    user_id: int
    reference: str
    category: TicketCategory
    priority: TicketPriority
    state: TicketState
    subject_fa: str
    assignee_id: int | None
    created_at: datetime
    updated_at: datetime
    message_count: int
    unread_for_agent: int
    unread_for_customer: int
    waiting_minutes: int | None

    @classmethod
    def from_ticket(cls, ticket: Ticket, now: datetime) -> TicketSummary:
        return cls(
            ticket_id=ticket.id,
            user_id=ticket.user_id,
            reference=ticket.reference,
            category=ticket.category,
            priority=ticket.priority,
            state=ticket.state,
            subject_fa=ticket.subject_fa,
            assignee_id=ticket.assignee_id,
            created_at=ticket.created_at,
            updated_at=ticket.updated_at,
            message_count=len(ticket.messages),
            unread_for_agent=ticket.unread_count_for_agent(),
            unread_for_customer=ticket.unread_count_for_customer(),
            waiting_minutes=ticket.waiting_minutes(now),
        )


@dataclass(frozen=True, slots=True)
class MessageView:
    message_id: str
    ticket_id: str
    kind: MessageKind
    body_fa: str
    author_id: int | None
    created_at: datetime
    attachment_count: int
    template_id: str | None
    is_read: bool

    @classmethod
    def from_message(cls, msg: Message) -> MessageView:
        return cls(
            message_id=msg.message_id,
            ticket_id=msg.ticket_id,
            kind=msg.kind,
            body_fa=msg.body_fa,
            author_id=msg.author_id,
            created_at=msg.created_at,
            attachment_count=len(msg.attachments),
            template_id=msg.template_id,
            is_read=msg.read_at is not None,
        )


class TicketService:
    """All ticket mutations. Collaborates with TicketRepository, TemplateRepository,
    EventPublisher, and SupportNotifier."""

    def __init__(
        self,
        *,
        tickets: TicketRepository,
        templates: TemplateRepository,
        clock: Clock,
        ids: IdGenerator,
        events: EventPublisher,
        notifier: SupportNotifier,
    ) -> None:
        self._tickets = tickets
        self._templates = templates
        self._clock = clock
        self._ids = ids
        self._events = events
        self._notifier = notifier

    # -- customer actions --------------------------------------------------

    def open_ticket(self, request: OpenTicketRequest) -> TicketSummary:
        """Create a new ticket and its first message."""
        now = self._clock.now()
        ticket_id = self._ids.new_id()
        message_id = self._ids.new_id()
        # The Jalali year, not the Gregorian one. The reference prints Jalali,
        # and the repository counts what it has already printed - passing 2026
        # here asked it how many references contain "2026" while every one of
        # them contains "1405", so the answer was always zero.
        year = _gregorian_to_jalali_year(now.year)
        sequence = self._tickets.next_sequence(year=year)
        reference = format_ticket_reference(year=year, sequence=sequence)

        ticket = Ticket.open(
            ticket_id,
            user_id=request.user_id,
            reference=reference,
            category=request.category,
            priority=request.priority,
            subject_fa=request.subject_fa,
            first_message_fa=request.first_message_fa,
            first_message_id=message_id,
            now=now,
            attachments=request.attachments,
        )
        self._tickets.save(ticket)
        self._events.publish_all(ticket.collect_events())
        self._notifier.notify_agent_new_ticket(ticket)
        return TicketSummary.from_ticket(ticket, now)

    def customer_reply(self, request: ReplyRequest) -> MessageView:
        """Customer sends a follow-up message."""
        now = self._clock.now()
        message_id = self._ids.new_id()
        ticket = self._tickets.get(request.ticket_id)
        msg = ticket.reply_by_customer(
            message_id=message_id,
            body_fa=request.body_fa,
            author_id=request.author_id,
            now=now,
            attachments=request.attachments,
        )
        self._tickets.save(ticket)
        self._events.publish_all(ticket.collect_events())
        self._notifier.notify_agent_customer_replied(ticket, request.body_fa)
        return MessageView.from_message(msg)

    # -- agent actions -----------------------------------------------------

    def agent_reply(self, request: ReplyRequest) -> MessageView:
        """Agent sends a visible reply (optionally from a template)."""
        now = self._clock.now()
        message_id = self._ids.new_id()
        ticket = self._tickets.get(request.ticket_id)

        template_id = request.template_id
        body = request.body_fa
        if template_id:
            try:
                tmpl = self._templates.get(template_id)
                tmpl.record_use()
                self._templates.save(tmpl)
                # If the agent didn't pass a body, use the template text.
                if not body.strip():
                    body = tmpl.body_fa
            except TemplateNotFound:
                template_id = None  # Graceful: just send the body without linking.

        msg = ticket.reply_by_agent(
            message_id=message_id,
            body_fa=body,
            author_id=request.author_id,
            now=now,
            attachments=request.attachments,
            template_id=template_id,
        )
        self._tickets.save(ticket)
        self._events.publish_all(ticket.collect_events())
        self._notifier.notify_customer_reply(ticket, body)
        return MessageView.from_message(msg)

    def add_note(self, request: NoteRequest) -> MessageView:
        """Agent writes an internal note."""
        now = self._clock.now()
        message_id = self._ids.new_id()
        ticket = self._tickets.get(request.ticket_id)
        msg = ticket.add_internal_note(
            message_id=message_id,
            body_fa=request.body_fa,
            author_id=request.author_id,
            now=now,
            attachments=request.attachments,
        )
        self._tickets.save(ticket)
        return MessageView.from_message(msg)

    def close_ticket(
        self, ticket_id: str, *, actor_id: int, closed_by_agent: bool
    ) -> TicketSummary:
        now = self._clock.now()
        ticket = self._tickets.get(ticket_id)
        already_closed = ticket.state.is_terminal()
        ticket.close(closed_by_agent=closed_by_agent, now=now)
        self._tickets.save(ticket)
        events = ticket.collect_events()
        self._events.publish_all(events)
        if closed_by_agent and not already_closed:
            self._notifier.notify_customer_closed(ticket)
        return TicketSummary.from_ticket(ticket, now)

    def change_priority(
        self, ticket_id: str, new_priority: TicketPriority, *, actor_id: int
    ) -> TicketSummary:
        now = self._clock.now()
        note_id = self._ids.new_id()
        ticket = self._tickets.get(ticket_id)
        ticket.change_priority(new_priority, actor_id=actor_id, note_id=note_id, now=now)
        self._tickets.save(ticket)
        self._events.publish_all(ticket.collect_events())
        return TicketSummary.from_ticket(ticket, now)

    def change_category(
        self, ticket_id: str, new_category: TicketCategory, *, actor_id: int
    ) -> TicketSummary:
        now = self._clock.now()
        note_id = self._ids.new_id()
        ticket = self._tickets.get(ticket_id)
        ticket.change_category(new_category, actor_id=actor_id, note_id=note_id, now=now)
        self._tickets.save(ticket)
        return TicketSummary.from_ticket(ticket, now)

    def assign_ticket(
        self, ticket_id: str, assignee_id: int | None, *, actor_id: int
    ) -> TicketSummary:
        now = self._clock.now()
        note_id = self._ids.new_id()
        ticket = self._tickets.get(ticket_id)
        ticket.assign(assignee_id, note_id=note_id, now=now)
        self._tickets.save(ticket)
        self._events.publish_all(ticket.collect_events())
        return TicketSummary.from_ticket(ticket, now)

    def mark_read(self, ticket_id: str, *, viewer_is_agent: bool) -> int:
        """Mark messages as read. Returns the count of messages newly marked."""
        now = self._clock.now()
        ticket = self._tickets.get(ticket_id)
        changed = ticket.mark_messages_read(viewer_is_agent=viewer_is_agent, now=now)
        if changed:
            self._tickets.save(ticket)
        return changed

    # -- queries -----------------------------------------------------------

    def list_for_user(
        self,
        user_id: int,
        *,
        state: TicketState | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[TicketSummary]:
        now = self._clock.now()
        tickets = self._tickets.for_user(user_id, state=state, limit=limit, offset=offset)
        return [TicketSummary.from_ticket(t, now) for t in tickets]

    def get_ticket(self, ticket_id: str) -> TicketSummary:
        now = self._clock.now()
        ticket = self._tickets.get(ticket_id)
        return TicketSummary.from_ticket(ticket, now)

    def get_messages(self, ticket_id: str, *, include_internal: bool = False) -> list[MessageView]:
        """History of a ticket. Agents see internal notes; customers do not."""
        ticket = self._tickets.get(ticket_id)
        msgs = ticket.messages
        if not include_internal:
            msgs = tuple(m for m in msgs if not m.is_internal)
        return [MessageView.from_message(m) for m in msgs]

    def queue(
        self,
        *,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        assignee_id: int | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[TicketSummary]:
        """The open-ticket queue for the admin panel."""
        now = self._clock.now()
        tickets = self._tickets.all_open(
            category=category,
            priority=priority,
            assignee_id=assignee_id,
            limit=limit,
            offset=offset,
        )
        return [TicketSummary.from_ticket(t, now) for t in tickets]


__all__ = [
    "MessageView",
    "NoteRequest",
    "OpenTicketRequest",
    "ReplyRequest",
    "TicketService",
    "TicketSummary",
]
