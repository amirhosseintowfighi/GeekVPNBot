"""Collaboration ports for the support services.

The application owns these interfaces; infrastructure implements them;
tests use in-memory fakes.

Identifier convention:
- ticket_id, message_id, template_id: str (short human-readable reference)
- user_id: int (Telegram user id)
- actor_id: int (agent Telegram or admin id)
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from geekvpn.domain.support.enums import TicketCategory, TicketPriority, TicketState
from geekvpn.domain.support.template import Template
from geekvpn.domain.support.ticket import Ticket


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime: ...


@runtime_checkable
class IdGenerator(Protocol):
    def new_id(self) -> str: ...


@runtime_checkable
class EventPublisher(Protocol):
    def publish_all(self, events: Sequence[object]) -> None: ...


@runtime_checkable
class TicketRepository(Protocol):
    def get(self, ticket_id: str) -> Ticket: ...

    """Raises TicketNotFound."""

    def save(self, ticket: Ticket) -> None: ...

    def for_user(
        self,
        user_id: int,
        *,
        state: TicketState | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Ticket]: ...

    def all_open(
        self,
        *,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        assignee_id: int | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[Ticket]: ...

    def search(
        self,
        query: str,
        *,
        user_id: int | None = None,
        state: TicketState | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[Ticket]: ...

    def next_sequence(self, *, year: int) -> int: ...

    """Returns an atomically incremented sequence number for the year."""

    def count_for_user(self, user_id: int, *, state: TicketState | None = None) -> int: ...

    def count_open(
        self,
        *,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        assignee_id: int | None = None,
    ) -> int: ...

    """Total matching the same filters as ``all_open``, for the admin pager."""


@runtime_checkable
class TemplateRepository(Protocol):
    def get(self, template_id: str) -> Template: ...

    """Raises TemplateNotFound."""

    def save(self, template: Template) -> None: ...

    def list_active(
        self,
        *,
        category: TicketCategory | None = None,
    ) -> list[Template]: ...

    def delete(self, template_id: str) -> None: ...


@runtime_checkable
class SupportNotifier(Protocol):
    """Sends messages to customers and agents via Telegram."""

    def notify_agent_new_ticket(
        self, ticket: Ticket, *, assignee_id: int | None = None
    ) -> None: ...

    def notify_customer_reply(self, ticket: Ticket, message_body_fa: str) -> None: ...

    def notify_customer_closed(self, ticket: Ticket) -> None: ...

    def notify_agent_customer_replied(self, ticket: Ticket, message_body_fa: str) -> None: ...


__all__ = [
    "Clock",
    "EventPublisher",
    "IdGenerator",
    "SupportNotifier",
    "TemplateRepository",
    "TicketRepository",
]
