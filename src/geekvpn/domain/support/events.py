"""Support domain events.

Naming: support.<thing>.<past_tense>.v1

Each event is the fact something happened. Downstream: the notifier listens
for TicketReplied to send a Telegram message; the outbox watches
TicketOpened to trigger first-reply SLA timers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from geekvpn.domain.base.events import DomainEvent
from geekvpn.domain.support.enums import MessageKind, TicketCategory, TicketPriority, TicketState


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketOpened(DomainEvent):
    """A new support conversation was started by a customer."""

    name: ClassVar[str] = "support.ticket.opened.v1"

    ticket_id: str
    user_id: int
    reference: str
    category: TicketCategory
    priority: TicketPriority
    subject_fa: str
    first_message_fa: str

    def payload(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "reference": self.reference,
            "category": str(self.category),
            "priority": str(self.priority),
            "subject_fa": self.subject_fa,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketReplied(DomainEvent):
    """A message was added to an existing ticket (by either party)."""

    name: ClassVar[str] = "support.ticket.replied.v1"

    ticket_id: str
    user_id: int
    message_id: str
    kind: MessageKind
    body_fa: str
    new_state: TicketState

    def payload(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "message_id": self.message_id,
            "kind": str(self.kind),
            "new_state": str(self.new_state),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketClosed(DomainEvent):
    name: ClassVar[str] = "support.ticket.closed.v1"

    ticket_id: str
    user_id: int
    closed_by_agent: bool

    def payload(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "closed_by_agent": self.closed_by_agent,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketPriorityChanged(DomainEvent):
    name: ClassVar[str] = "support.ticket.priority_changed.v1"

    ticket_id: str
    user_id: int
    old_priority: TicketPriority
    new_priority: TicketPriority

    def payload(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "old_priority": str(self.old_priority),
            "new_priority": str(self.new_priority),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class TicketAssigned(DomainEvent):
    name: ClassVar[str] = "support.ticket.assigned.v1"

    ticket_id: str
    user_id: int
    assignee_id: int | None

    def payload(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "assignee_id": self.assignee_id,
        }


__all__ = [
    "TicketAssigned",
    "TicketClosed",
    "TicketOpened",
    "TicketPriorityChanged",
    "TicketReplied",
]
