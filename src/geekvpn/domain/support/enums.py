"""Support domain enums.

Two dimensions of routing: priority (how fast someone must answer) and
category (who is best placed to answer). They are separate because an urgent
billing question is different from an urgent connection question, and either
operator might be online.
"""

from __future__ import annotations

import enum


class TicketPriority(enum.StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

    def label_fa(self) -> str:
        return {
            TicketPriority.LOW: "\u06a9\u0645",
            TicketPriority.NORMAL: "\u0639\u0627\u062f\u06cc",
            TicketPriority.HIGH: "\u0632\u06cc\u0627\u062f",
            TicketPriority.URGENT: "\u0641\u0648\u0631\u06cc",
        }[self]

    def sla_minutes(self) -> int:
        """Target first-reply time. Not a hard limit: a promise to aim for."""
        return {
            TicketPriority.LOW: 1440,
            TicketPriority.NORMAL: 480,
            TicketPriority.HIGH: 120,
            TicketPriority.URGENT: 30,
        }[self]


class TicketCategory(enum.StrEnum):
    CONNECTION = "connection"
    PAYMENT = "payment"
    ACCOUNT = "account"
    SPEED = "speed"
    TECHNICAL = "technical"
    OTHER = "other"

    def label_fa(self) -> str:
        return {
            TicketCategory.CONNECTION: "\u0627\u062a\u0635\u0627\u0644",
            TicketCategory.PAYMENT: "\u067e\u0631\u062f\u0627\u062e\u062a",
            TicketCategory.ACCOUNT: "\u062d\u0633\u0627\u0628 \u06a9\u0627\u0631\u0628\u0631\u06cc",
            TicketCategory.SPEED: "\u0633\u0631\u0639\u062a",
            TicketCategory.TECHNICAL: "\u0641\u0646\u06cc",
            TicketCategory.OTHER: "\u0633\u0627\u06cc\u0631",
        }[self]


class TicketState(enum.StrEnum):
    """Lifecycle of a support ticket.

    The state is the queue each ticket sits in:
    - OPEN: needs a support agent to read and reply.
    - WAITING_USER: the agent replied; the customer owes the next move.
    - ANSWERED: resolved from the agent's side; will auto-close unless re-opened.
    - CLOSED: conversation is done.
    """

    OPEN = "open"
    WAITING_USER = "waiting_user"
    ANSWERED = "answered"
    CLOSED = "closed"

    def awaits_agent(self) -> bool:
        return self is TicketState.OPEN

    def awaits_customer(self) -> bool:
        return self is TicketState.WAITING_USER

    def is_terminal(self) -> bool:
        return self is TicketState.CLOSED


class MessageKind(enum.StrEnum):
    """What kind of message was added to a ticket.

    CUSTOMER and SUPPORT are the two sides of the conversation and appear in
    the customer-facing thread. NOTE is visible only to agents and never to
    the customer. STATUS_CHANGE is an automatic entry added when priority,
    category, or state changes.
    """

    CUSTOMER = "customer"
    SUPPORT = "support"
    NOTE = "note"
    STATUS_CHANGE = "status_change"

    def is_internal(self) -> bool:
        return self in (MessageKind.NOTE, MessageKind.STATUS_CHANGE)

    def is_visible_to_customer(self) -> bool:
        return self in (MessageKind.CUSTOMER, MessageKind.SUPPORT)


__all__ = [
    "MessageKind",
    "TicketCategory",
    "TicketPriority",
    "TicketState",
]
