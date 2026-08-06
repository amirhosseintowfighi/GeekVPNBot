"""Synchronous support repositories, shaped to ``application/support/ports.py``.

The services in ``application/support`` are synchronous, so they cannot be
handed the async repositories in ``support.py``. See the module docstring of
``sync_payments.py`` for why both families exist.

One behavioural note that is easy to miss: ``get`` raises rather than returning
``None``. That is the port's contract - it is typed ``-> Ticket``. A ticket id
that does not resolve is a bug or a tampered request, never a normal branch.

House rules: never commit, filter in SQL, re-read before write.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from geekvpn.domain.base.errors import NotFoundError
from geekvpn.domain.support.enums import TicketCategory, TicketPriority, TicketState
from geekvpn.domain.support.template import Template
from geekvpn.domain.support.ticket import Ticket
from geekvpn.infrastructure.persistence.mappers.support import (
    message_apply,
    message_to_row,
    template_apply,
    template_to_domain,
    template_to_row,
    ticket_apply,
    ticket_to_domain,
    ticket_to_row,
)
from geekvpn.infrastructure.persistence.models.support import (
    ReplyTemplateModel,
    TicketMessageModel,
    TicketModel,
)

#: A ticket nobody has finished with yet.
OPEN_STATES = (
    TicketState.OPEN.value,
    TicketState.WAITING_USER.value,
    TicketState.ANSWERED.value,
)


class SyncTicketRepository:
    """``application.support.ports.TicketRepository``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _messages(self, ticket_id: str) -> list[TicketMessageModel]:
        stmt = (
            select(TicketMessageModel)
            .where(TicketMessageModel.ticket_id == ticket_id)
            .order_by(TicketMessageModel.sent_at, TicketMessageModel.id)
        )
        return list(self._session.execute(stmt).scalars().all())

    def _hydrate(self, row: TicketModel) -> Ticket:
        return ticket_to_domain(row, messages=self._messages(row.id))

    def _hydrate_many(self, rows: Sequence[TicketModel]) -> list[Ticket]:
        return [self._hydrate(row) for row in rows]

    def get(self, ticket_id: str) -> Ticket:
        row = self._session.get(TicketModel, ticket_id)
        if row is None:
            raise NotFoundError("Ticket not found.", ticket_id=ticket_id)
        return self._hydrate(row)

    def save(self, ticket: Ticket) -> None:
        """Upsert the ticket and reconcile its messages.

        Messages are upserted rather than only appended because ``mark_read``
        changes ``read_at`` on messages that already exist. Insert-only here
        would silently lose every read receipt.
        """
        row = self._session.get(TicketModel, ticket.id)
        if row is None:
            self._session.add(ticket_to_row(ticket))
        else:
            ticket_apply(row, ticket)

        existing = {model.id: model for model in self._messages(ticket.id)}
        for message in ticket.messages:
            current = existing.get(message.message_id)
            if current is None:
                self._session.add(message_to_row(message))
            else:
                message_apply(current, message)
        self._session.flush()

    def for_user(
        self,
        user_id: int,
        *,
        state: TicketState | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Ticket]:
        stmt = select(TicketModel).where(TicketModel.user_id == user_id)
        if state is not None:
            stmt = stmt.where(TicketModel.state == state.value)
        stmt = (
            stmt.order_by(TicketModel.opened_at.desc(), TicketModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return self._hydrate_many(self._session.execute(stmt).scalars().all())

    def all_open(
        self,
        *,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        assignee_id: int | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[Ticket]:
        """The agent queue: longest wait first.

        Ordering by ``waiting_since`` rather than by priority is on purpose.
        Priority already decides the SLA; if the queue also sorted by it, a
        steady trickle of urgent tickets would starve every normal one
        indefinitely.
        """
        stmt = select(TicketModel).where(TicketModel.state.in_(OPEN_STATES))
        if category is not None:
            stmt = stmt.where(TicketModel.category == category.value)
        if priority is not None:
            stmt = stmt.where(TicketModel.priority == priority.value)
        if assignee_id is not None:
            stmt = stmt.where(TicketModel.assignee_id == assignee_id)
        stmt = (
            stmt.order_by(TicketModel.waiting_since.asc().nullslast(), TicketModel.opened_at.asc())
            .limit(limit)
            .offset(offset)
        )
        return self._hydrate_many(self._session.execute(stmt).scalars().all())

    def count_open(
        self,
        *,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        assignee_id: int | None = None,
    ) -> int:
        """How many tickets the queue holds, with the same filters as ``all_open``.

        The admin queue is paginated, and a pager needs a real total. Returning
        the length of the current page instead would tell an agent looking at 25
        tickets that there are exactly 25 - which is precisely wrong when there
        are 300 and someone is deciding whether to stay late.
        """
        stmt = (
            select(func.count()).select_from(TicketModel).where(TicketModel.state.in_(OPEN_STATES))
        )
        if category is not None:
            stmt = stmt.where(TicketModel.category == category.value)
        if priority is not None:
            stmt = stmt.where(TicketModel.priority == priority.value)
        if assignee_id is not None:
            stmt = stmt.where(TicketModel.assignee_id == assignee_id)
        return int(self._session.execute(stmt).scalar_one())

    def search(
        self,
        query: str,
        *,
        user_id: int | None = None,
        state: TicketState | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[Ticket]:
        """Search subject, reference and message bodies.

        ``ilike`` with a leading wildcard cannot use a b-tree index, which is
        acceptable at this table size and honest about its cost. If the ticket
        table ever grows past a few hundred thousand rows this becomes a
        trigram index, not a bigger LIMIT.
        """
        pattern = f"%{query.strip()}%"
        in_messages = (
            select(TicketMessageModel.ticket_id)
            .where(TicketMessageModel.body_fa.ilike(pattern))
            .scalar_subquery()
        )
        stmt = select(TicketModel).where(
            or_(
                TicketModel.subject_fa.ilike(pattern),
                TicketModel.reference.ilike(pattern),
                TicketModel.id.in_(in_messages),
            )
        )
        if user_id is not None:
            stmt = stmt.where(TicketModel.user_id == user_id)
        if state is not None:
            stmt = stmt.where(TicketModel.state == state.value)
        stmt = (
            stmt.order_by(TicketModel.opened_at.desc(), TicketModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return self._hydrate_many(self._session.execute(stmt).scalars().all())

    def next_sequence(self, *, year: int) -> int:
        """How many references already carry this Jalali year.

        Matching the year as a substring keeps the reference format
        (``SUP-1405-000042``) the service's business, not the repository's.
        """
        stmt = (
            select(func.count())
            .select_from(TicketModel)
            .where(TicketModel.reference.like(f"%{year}%"))
        )
        return int(self._session.execute(stmt).scalar_one())

    def count_for_user(self, user_id: int, *, state: TicketState | None = None) -> int:
        stmt = select(func.count()).select_from(TicketModel).where(TicketModel.user_id == user_id)
        if state is not None:
            stmt = stmt.where(TicketModel.state == state.value)
        return int(self._session.execute(stmt).scalar_one())


class SyncTemplateRepository:
    """``application.support.ports.TemplateRepository``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, template_id: str) -> Template:
        row = self._session.get(ReplyTemplateModel, template_id)
        if row is None:
            raise NotFoundError("Reply template not found.", template_id=template_id)
        return template_to_domain(row)

    def save(self, template: Template) -> None:
        row = self._session.get(ReplyTemplateModel, template.id)
        if row is None:
            self._session.add(template_to_row(template))
        else:
            template_apply(row, template)
        self._session.flush()

    def list_active(self, *, category: TicketCategory | None = None) -> list[Template]:
        """Active templates, optionally narrowed to one category.

        An empty ``categories`` array means 'applies everywhere', so it must
        match every category filter rather than none of them.
        """
        stmt = select(ReplyTemplateModel).where(ReplyTemplateModel.active.is_(True))
        if category is not None:
            stmt = stmt.where(
                or_(
                    func.jsonb_array_length(ReplyTemplateModel.categories) == 0,
                    ReplyTemplateModel.categories.contains([category.value]),
                )
            )
        stmt = stmt.order_by(ReplyTemplateModel.use_count.desc(), ReplyTemplateModel.title_fa)
        return [template_to_domain(row) for row in self._session.execute(stmt).scalars().all()]

    def delete(self, template_id: str) -> None:
        row = self._session.get(ReplyTemplateModel, template_id)
        if row is None:
            raise NotFoundError("Reply template not found.", template_id=template_id)
        self._session.delete(row)
        self._session.flush()


__all__ = ["OPEN_STATES", "SyncTemplateRepository", "SyncTicketRepository"]
