"""In-memory fakes for support services."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

from geekvpn.domain.support.enums import TicketCategory, TicketPriority, TicketState
from geekvpn.domain.support.errors import TemplateNotFound, TicketNotFound
from geekvpn.domain.support.template import Template
from geekvpn.domain.support.ticket import Ticket

EPOCH = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
AGENT_ID = 9001
USER_ID = 1001


class FakeClock:
    def __init__(self, now: datetime = EPOCH) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, minutes: int) -> None:
        from datetime import timedelta

        self._now = self._now + timedelta(minutes=minutes)


class FakeIds:
    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"id-{self._counter:04d}"


class FakeEvents:
    def __init__(self) -> None:
        self.published: list[object] = []

    def publish_all(self, events: Sequence[object]) -> None:
        self.published.extend(events)

    def of_type(self, cls):
        return [e for e in self.published if isinstance(e, cls)]


class FakeNotifier:
    def __init__(self) -> None:
        self.new_ticket_calls: list[Ticket] = []
        self.customer_reply_calls: list[tuple[Ticket, str]] = []
        self.customer_closed_calls: list[Ticket] = []
        self.agent_reply_calls: list[tuple[Ticket, str]] = []

    def notify_agent_new_ticket(self, ticket: Ticket, *, assignee_id=None) -> None:
        self.new_ticket_calls.append(ticket)

    def notify_customer_reply(self, ticket: Ticket, message_body_fa: str) -> None:
        self.customer_reply_calls.append((ticket, message_body_fa))

    def notify_customer_closed(self, ticket: Ticket) -> None:
        self.customer_closed_calls.append(ticket)

    def notify_agent_customer_replied(self, ticket: Ticket, message_body_fa: str) -> None:
        self.agent_reply_calls.append((ticket, message_body_fa))


class FakeTicketRepository:
    def __init__(self) -> None:
        self._store: dict[str, Ticket] = {}
        self._sequences: dict[int, int] = defaultdict(int)

    def get(self, ticket_id: str) -> Ticket:
        try:
            return self._store[ticket_id]
        except KeyError:
            raise TicketNotFound(ticket_id) from None

    def save(self, ticket: Ticket) -> None:
        self._store[ticket.id] = ticket

    def for_user(
        self,
        user_id: int,
        *,
        state: TicketState | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Ticket]:
        results = [
            t
            for t in self._store.values()
            if t.user_id == user_id and (state is None or t.state is state)
        ]
        results.sort(key=lambda t: t.updated_at, reverse=True)
        return results[offset : offset + limit]

    def all_open(
        self,
        *,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        assignee_id: int | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[Ticket]:
        results = [
            t
            for t in self._store.values()
            if t.state.awaits_agent()
            and (category is None or t.category is category)
            and (priority is None or t.priority is priority)
            and (assignee_id is None or t.assignee_id == assignee_id)
        ]
        results.sort(key=lambda t: t.created_at)
        return results[offset : offset + limit]

    def search(
        self,
        query: str,
        *,
        user_id: int | None = None,
        state: TicketState | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[Ticket]:
        q = query.lower()
        results = []
        for t in self._store.values():
            if user_id is not None and t.user_id != user_id:
                continue
            if state is not None and t.state is not state:
                continue
            text = (
                t.subject_fa + " " + t.reference + " ".join(m.body_fa for m in t.messages)
            ).lower()
            if q in text:
                results.append(t)
        return results[offset : offset + limit]

    def next_sequence(self, *, year: int) -> int:
        self._sequences[year] += 1
        return self._sequences[year]

    def count_for_user(self, user_id: int, *, state: TicketState | None = None) -> int:
        return len(self.for_user(user_id, state=state, limit=10_000))


class FakeTemplateRepository:
    def __init__(self) -> None:
        self._store: dict[str, Template] = {}

    def get(self, template_id: str) -> Template:
        try:
            return self._store[template_id]
        except KeyError:
            raise TemplateNotFound(f"Template {template_id!r} not found.") from None

    def save(self, template: Template) -> None:
        self._store[template.id] = template

    def list_active(self, *, category: TicketCategory | None = None) -> list[Template]:
        return [
            t
            for t in self._store.values()
            if t.is_active and (category is None or t.applies_to(category))
        ]

    def delete(self, template_id: str) -> None:
        self._store.pop(template_id, None)
