"""The Ticket aggregate — the core of the support system.

One ticket is one conversation between a customer and the support team.
Messages are the conversation's content; they are owned by the ticket and
never live independently. The ticket's state is driven entirely by who spoke
last and what they said.

Key invariants that the aggregate enforces:

- A closed ticket cannot receive new messages (TicketClosed).
- An internal note never changes the visible conversation or the customer-
  facing state.
- Re-opening a closed ticket is allowed once (a customer replying to a closed
  ticket is a normal event, not an error).
- Priority and category can be changed by an agent at any time while the
  ticket is open; each change appends a STATUS_CHANGE message so the audit
  trail stays inside the ticket, not only in an external log.
- Attachments are file references, not content. Storing binary data inside an
  aggregate would make hydration unacceptably slow.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from geekvpn.domain.base.entity import AggregateRoot
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
from geekvpn.domain.support.events import (
    TicketAssigned,
    TicketOpened,
    TicketPriorityChanged,
    TicketReplied,
)
from geekvpn.domain.support.events import (
    TicketClosed as TicketClosedEvent,
)

MIN_MESSAGE: Final[int] = 5
MAX_ATTACHMENTS: Final[int] = 5

TICKET_PREFIX: Final[str] = "SUP"


def format_ticket_reference(*, year: int, sequence: int) -> str:
    """``SUP-1405-000042``. The year is Jalali, as printed.

    Here rather than in the service because the repository has to build the
    same string to count the ones already issued, and a prefix written out in
    two places is two prefixes as soon as one is edited.
    """
    if sequence <= 0:
        raise ValueError(f"sequence must be positive, got {sequence}")
    return f"{TICKET_PREFIX}-{year:04d}-{sequence:06d}"


ALLOWED_MIME_TYPES: frozenset[str] = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
        "application/pdf",
        "video/mp4",
    }
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Attachment:
    """A reference to a file stored externally.

    ``file_id`` is a Telegram file id or a storage locator from the
    object store. ``mime_type`` is validated on construction so an agent
    cannot accidentally open an executable attachment in the admin panel.
    """

    file_id: str
    mime_type: str
    size_bytes: int | None = None
    original_name: str | None = None

    def __post_init__(self) -> None:
        if not self.file_id.strip():
            raise InvalidAttachment("Attachment file_id is blank.")
        if self.mime_type not in ALLOWED_MIME_TYPES:
            raise InvalidAttachment(
                f"MIME type {self.mime_type!r} is not allowed.",
                allowed=sorted(ALLOWED_MIME_TYPES),
            )


@dataclass(slots=True, kw_only=True)
class Message:
    """One entry in a support conversation.

    Mutable only for the ``read_at`` timestamp: everything else is immutable
    once written. Using a dataclass rather than a frozen one because we need
    to mark messages as read without rebuilding them.
    """

    message_id: str
    ticket_id: str
    kind: MessageKind
    body_fa: str
    author_id: int | None  # None for system-generated STATUS_CHANGE messages
    created_at: datetime
    attachments: tuple[Attachment, ...] = field(default_factory=tuple)
    template_id: str | None = None
    read_at: datetime | None = None

    def mark_read(self, at: datetime) -> None:
        if self.read_at is None:
            self.read_at = at

    @property
    def is_internal(self) -> bool:
        return self.kind.is_internal()

    @property
    def is_unread(self) -> bool:
        return self.read_at is None


class Ticket(AggregateRoot[str]):
    """One support conversation.

    The id is a short alphanumeric string ("SUP-1405-000042") that appears in
    the Telegram UI and on the admin panel. UUIDs are reserved for database
    primary keys at the infrastructure layer.
    """

    __slots__ = (
        "_messages",
        "assignee_id",
        "category",
        "created_at",
        "priority",
        "reference",
        "state",
        "subject_fa",
        "updated_at",
        "user_id",
    )

    def __init__(
        self,
        ticket_id: str,
        *,
        user_id: int,
        reference: str,
        category: TicketCategory,
        priority: TicketPriority,
        subject_fa: str,
        state: TicketState,
        created_at: datetime,
        updated_at: datetime,
        assignee_id: int | None = None,
        messages: list[Message] | None = None,
    ) -> None:
        super().__init__(ticket_id)
        self.user_id = user_id
        self.reference = reference
        self.category = category
        self.priority = priority
        self.state = state
        self.subject_fa = subject_fa
        self.assignee_id = assignee_id
        self.created_at = created_at
        self.updated_at = updated_at
        self._messages: list[Message] = messages or []

    # -- factories ---------------------------------------------------------

    @classmethod
    def open(
        cls,
        ticket_id: str,
        *,
        user_id: int,
        reference: str,
        category: TicketCategory,
        priority: TicketPriority,
        subject_fa: str,
        first_message_fa: str,
        first_message_id: str,
        now: datetime,
        attachments: Sequence[Attachment] = (),
    ) -> Ticket:
        """Create a new ticket and its first customer message."""
        if len(first_message_fa.strip()) < MIN_MESSAGE:
            raise MessageTooShort(minimum=MIN_MESSAGE, actual=len(first_message_fa.strip()))
        if len(attachments) > MAX_ATTACHMENTS:
            raise TooManyAttachments(
                f"At most {MAX_ATTACHMENTS} attachments per message.",
                limit=MAX_ATTACHMENTS,
            )

        ticket = cls(
            ticket_id,
            user_id=user_id,
            reference=reference,
            category=category,
            priority=priority,
            subject_fa=subject_fa,
            state=TicketState.OPEN,
            created_at=now,
            updated_at=now,
        )
        first = Message(
            message_id=first_message_id,
            ticket_id=ticket_id,
            kind=MessageKind.CUSTOMER,
            body_fa=first_message_fa,
            author_id=user_id,
            created_at=now,
            attachments=tuple(attachments),
        )
        ticket._messages.append(first)
        ticket.record(
            TicketOpened(
                ticket_id=ticket_id,
                user_id=user_id,
                reference=reference,
                category=category,
                priority=priority,
                subject_fa=subject_fa,
                first_message_fa=first_message_fa,
            )
        )
        return ticket

    # -- reads -------------------------------------------------------------

    @property
    def messages(self) -> tuple[Message, ...]:
        return tuple(self._messages)

    def customer_messages(self) -> list[Message]:
        """Messages visible to the customer."""
        return [m for m in self._messages if m.kind.is_visible_to_customer()]

    def internal_notes(self) -> list[Message]:
        return [m for m in self._messages if m.kind is MessageKind.NOTE]

    def unread_count_for_customer(self) -> int:
        """Support replies the customer has not seen yet."""
        return sum(1 for m in self._messages if m.kind is MessageKind.SUPPORT and m.is_unread)

    def unread_count_for_agent(self) -> int:
        """Customer messages the support team has not read yet."""
        return sum(1 for m in self._messages if m.kind is MessageKind.CUSTOMER and m.is_unread)

    def waiting_minutes(self, now: datetime) -> int | None:
        """Minutes the oldest unread customer message has been waiting."""
        candidates = [m for m in self._messages if m.kind is MessageKind.CUSTOMER and m.is_unread]
        if not candidates:
            return None
        oldest = min(candidates, key=lambda m: m.created_at)
        return max(0, int((now - oldest.created_at).total_seconds() / 60))

    def last_reply_at(self) -> datetime | None:
        visible = [m for m in self._messages if m.kind.is_visible_to_customer()]
        return visible[-1].created_at if visible else None

    # -- customer actions --------------------------------------------------

    def reply_by_customer(
        self,
        *,
        message_id: str,
        body_fa: str,
        author_id: int,
        now: datetime,
        attachments: Sequence[Attachment] = (),
    ) -> Message:
        """The customer sends another message, re-opening a closed ticket."""
        if self.state.is_terminal():
            # A reply to a closed ticket re-opens it rather than being refused.
            # Refusing would force the customer to start over, which loses the
            # conversation history and makes the problem look new.
            self.state = TicketState.OPEN
        self._validate_body(body_fa)
        self._validate_attachments(attachments)

        msg = self._append_message(
            message_id=message_id,
            kind=MessageKind.CUSTOMER,
            body_fa=body_fa,
            author_id=author_id,
            now=now,
            attachments=attachments,
        )
        self.state = TicketState.OPEN
        self.updated_at = now
        self.record(
            TicketReplied(
                ticket_id=self.id,
                user_id=self.user_id,
                message_id=message_id,
                kind=MessageKind.CUSTOMER,
                body_fa=body_fa,
                new_state=self.state,
            )
        )
        return msg

    # -- agent actions -----------------------------------------------------

    def reply_by_agent(
        self,
        *,
        message_id: str,
        body_fa: str,
        author_id: int,
        now: datetime,
        attachments: Sequence[Attachment] = (),
        template_id: str | None = None,
    ) -> Message:
        """An agent sends a visible reply."""
        if self.state.is_terminal():
            raise TicketClosed(self.id)
        self._validate_body(body_fa)
        self._validate_attachments(attachments)

        msg = self._append_message(
            message_id=message_id,
            kind=MessageKind.SUPPORT,
            body_fa=body_fa,
            author_id=author_id,
            now=now,
            attachments=attachments,
            template_id=template_id,
        )
        self.state = TicketState.WAITING_USER
        self.updated_at = now
        self.record(
            TicketReplied(
                ticket_id=self.id,
                user_id=self.user_id,
                message_id=message_id,
                kind=MessageKind.SUPPORT,
                body_fa=body_fa,
                new_state=self.state,
            )
        )
        return msg

    def add_internal_note(
        self,
        *,
        message_id: str,
        body_fa: str,
        author_id: int,
        now: datetime,
        attachments: Sequence[Attachment] = (),
    ) -> Message:
        """An agent writes a note only colleagues can see.

        Notes never change the state from the customer's point of view, and
        never appear in the customer-facing thread.
        """
        if self.state.is_terminal():
            raise TicketClosed(self.id)
        self._validate_body(body_fa)
        self._validate_attachments(attachments)

        msg = self._append_message(
            message_id=message_id,
            kind=MessageKind.NOTE,
            body_fa=body_fa,
            author_id=author_id,
            now=now,
            attachments=attachments,
        )
        self.updated_at = now
        # Internal notes deliberately do not emit a domain event, so the
        # customer's Telegram notification is not triggered.
        return msg

    def close(self, *, closed_by_agent: bool, now: datetime) -> None:
        """Mark the conversation done."""
        if self.state.is_terminal():
            return  # Idempotent: two admins clicking close is harmless.
        self.state = TicketState.CLOSED
        self.updated_at = now
        self.record(
            TicketClosedEvent(
                ticket_id=self.id,
                user_id=self.user_id,
                closed_by_agent=closed_by_agent,
            )
        )

    def change_priority(
        self, new_priority: TicketPriority, *, actor_id: int, note_id: str, now: datetime
    ) -> None:
        if self.state.is_terminal():
            raise TicketClosed(self.id)
        if new_priority is self.priority:
            return
        old = self.priority
        self.priority = new_priority
        self.updated_at = now
        body = (
            f"\u0627\u0648\u0644\u0648\u06cc\u062a: {old.label_fa()} "
            f"\u2192 {new_priority.label_fa()}"
        )
        self._messages.append(
            Message(
                message_id=note_id,
                ticket_id=self.id,
                kind=MessageKind.STATUS_CHANGE,
                body_fa=body,
                author_id=actor_id,
                created_at=now,
            )
        )
        self.record(
            TicketPriorityChanged(
                ticket_id=self.id,
                user_id=self.user_id,
                old_priority=old,
                new_priority=new_priority,
            )
        )

    def change_category(
        self, new_category: TicketCategory, *, actor_id: int, note_id: str, now: datetime
    ) -> None:
        if self.state.is_terminal():
            raise TicketClosed(self.id)
        if new_category is self.category:
            return
        old_label = self.category.label_fa()
        self.category = new_category
        self.updated_at = now
        body = f"\u062f\u0633\u062a\u0647: {old_label} \u2192 {new_category.label_fa()}"
        self._messages.append(
            Message(
                message_id=note_id,
                ticket_id=self.id,
                kind=MessageKind.STATUS_CHANGE,
                body_fa=body,
                author_id=actor_id,
                created_at=now,
            )
        )

    def assign(self, assignee_id: int | None, *, note_id: str, now: datetime) -> None:
        if self.state.is_terminal():
            raise TicketClosed(self.id)
        if self.assignee_id == assignee_id:
            return
        self.assignee_id = assignee_id
        self.updated_at = now
        self.record(
            TicketAssigned(
                ticket_id=self.id,
                user_id=self.user_id,
                assignee_id=assignee_id,
            )
        )

    def mark_messages_read(self, *, viewer_is_agent: bool, now: datetime) -> int:
        """Mark the relevant unread messages as read. Returns the count changed."""
        changed = 0
        for msg in self._messages:
            if msg.is_unread and (
                (viewer_is_agent and msg.kind is MessageKind.CUSTOMER)
                or (not viewer_is_agent and msg.kind is MessageKind.SUPPORT)
            ):
                msg.mark_read(now)
                changed += 1
        return changed

    # -- private -----------------------------------------------------------

    def _validate_body(self, body: str) -> None:
        stripped = body.strip()
        if len(stripped) < MIN_MESSAGE:
            raise MessageTooShort(minimum=MIN_MESSAGE, actual=len(stripped))

    def _validate_attachments(self, attachments: Sequence[Attachment]) -> None:
        if len(attachments) > MAX_ATTACHMENTS:
            raise TooManyAttachments(
                f"At most {MAX_ATTACHMENTS} attachments per message.",
                limit=MAX_ATTACHMENTS,
            )

    def _append_message(
        self,
        *,
        message_id: str,
        kind: MessageKind,
        body_fa: str,
        author_id: int | None,
        now: datetime,
        attachments: Sequence[Attachment] = (),
        template_id: str | None = None,
    ) -> Message:
        msg = Message(
            message_id=message_id,
            ticket_id=self.id,
            kind=kind,
            body_fa=body_fa,
            author_id=author_id,
            created_at=now,
            attachments=tuple(attachments),
            template_id=template_id,
        )
        self._messages.append(msg)
        return msg


__all__ = [
    "ALLOWED_MIME_TYPES",
    "MAX_ATTACHMENTS",
    "MIN_MESSAGE",
    "Attachment",
    "Message",
    "Ticket",
]
