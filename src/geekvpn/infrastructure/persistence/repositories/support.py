"""Support repositories: tickets, their transcripts, and reply templates.

A ticket is loaded with its whole transcript. Support conversations are short -
tens of messages, not thousands - and every screen that shows a ticket shows
the conversation, so paginating it would add a second round trip to every
single view in exchange for nothing.

Messages are append-only apart from ``read_at``. Editing what a customer said
would destroy the value of the transcript as evidence, which is the reason the
transcript exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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

#: Tickets an agent still owes an answer on.
OPEN_STATES = (TicketState.OPEN.value, TicketState.WAITING_USER.value, TicketState.ANSWERED.value)


class SqlAlchemyTicketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _messages(self, ticket_id: str) -> Sequence[TicketMessageModel]:
        stmt = (
            select(TicketMessageModel)
            .where(TicketMessageModel.ticket_id == ticket_id)
            .order_by(TicketMessageModel.sent_at, TicketMessageModel.id)
        )
        return (await self._session.execute(stmt)).scalars().all()

    async def get(self, ticket_id: str) -> Ticket | None:
        row = await self._session.get(TicketModel, ticket_id)
        if row is None:
            return None
        return ticket_to_domain(row, messages=await self._messages(ticket_id))

    async def get_by_reference(self, reference: str) -> Ticket | None:
        stmt = select(TicketModel).where(TicketModel.reference == reference)
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return None
        return ticket_to_domain(row, messages=await self._messages(row.id))

    async def list_for_user(
        self, user_id: int, *, limit: int = 20, offset: int = 0
    ) -> Sequence[Ticket]:
        """Header rows only.

        The customer's ticket list shows subject, state and last activity, and
        loading every transcript to render it would be a page of queries.
        """
        stmt = (
            select(TicketModel)
            .where(TicketModel.user_id == user_id)
            .order_by(TicketModel.opened_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [ticket_to_domain(row) for row in rows]

    async def search(
        self,
        *,
        state: TicketState | None = None,
        category: TicketCategory | None = None,
        priority: TicketPriority | None = None,
        assignee_id: int | None = None,
        unassigned: bool = False,
        text: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> Sequence[Ticket]:
        stmt: Select[Any] = select(TicketModel)
        if state is not None:
            stmt = stmt.where(TicketModel.state == state.value)
        if category is not None:
            stmt = stmt.where(TicketModel.category == category.value)
        if priority is not None:
            stmt = stmt.where(TicketModel.priority == priority.value)
        if unassigned:
            stmt = stmt.where(TicketModel.assignee_id.is_(None))
        elif assignee_id is not None:
            stmt = stmt.where(TicketModel.assignee_id == assignee_id)
        if text:
            # Subject and reference only. Searching message bodies needs a
            # full-text index; a LIKE over every transcript would table-scan
            # the largest table in the schema on every keystroke.
            pattern = f"%{text}%"
            stmt = stmt.where(
                or_(
                    TicketModel.subject_fa.ilike(pattern),
                    TicketModel.reference.ilike(pattern),
                )
            )
        stmt = stmt.order_by(TicketModel.opened_at.desc()).limit(limit).offset(offset)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [ticket_to_domain(row) for row in rows]

    async def count_open(self) -> int:
        stmt = (
            select(func.count()).select_from(TicketModel).where(TicketModel.state.in_(OPEN_STATES))
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_breaching_sla(self, *, now: datetime, limit: int = 50) -> Sequence[Ticket]:
        """Waiting on us, oldest wait first.

        The SLA threshold itself depends on priority and lives in the domain,
        so this returns candidates ordered by wait and lets the caller apply
        ``TicketPriority.sla_minutes()`` rather than duplicating the ladder in
        SQL where it would silently drift.
        """
        stmt = (
            select(TicketModel)
            .where(
                TicketModel.state.in_((TicketState.OPEN.value, TicketState.ANSWERED.value)),
                TicketModel.waiting_since.is_not(None),
                TicketModel.waiting_since <= now,
            )
            .order_by(TicketModel.waiting_since)
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [ticket_to_domain(row) for row in rows]

    async def add(self, ticket: Ticket) -> None:
        self._session.add(ticket_to_row(ticket))
        # The parent alone first. `support_messages.ticket_id` is a foreign key
        # to this row and the two models carry no `relationship()`, so nothing
        # tells SQLAlchemy which insert has to come first - and it chose the
        # child. Same bug, same shape, as the synchronous repository.
        await self._session.flush()
        for message in ticket.messages:
            self._session.add(message_to_row(message))
        await self._session.flush()

    async def update(self, ticket: Ticket) -> None:
        row = await self._session.get(TicketModel, ticket.id)
        if row is None:
            raise NotFoundError("Ticket not found.", ticket_id=ticket.id)
        ticket_apply(row, ticket)
        stored = {model.id: model for model in await self._messages(ticket.id)}
        for message in ticket.messages:
            existing = stored.get(message.message_id)
            if existing is None:
                self._session.add(message_to_row(message))
            else:
                # Only read_at can legitimately change; message_apply enforces
                # that, so a bug elsewhere cannot rewrite a transcript.
                message_apply(existing, message)
        await self._session.flush()


class SqlAlchemyTemplateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, template_id: str) -> Template | None:
        row = await self._session.get(ReplyTemplateModel, template_id)
        return template_to_domain(row) if row else None

    async def list_all(self, *, active_only: bool = True) -> Sequence[Template]:
        stmt: Select[Any] = select(ReplyTemplateModel).order_by(
            ReplyTemplateModel.use_count.desc(), ReplyTemplateModel.title_fa
        )
        if active_only:
            stmt = stmt.where(ReplyTemplateModel.active.is_(True))
        rows = (await self._session.execute(stmt)).scalars().all()
        return [template_to_domain(row) for row in rows]

    async def list_for_category(self, category: TicketCategory) -> Sequence[Template]:
        """Templates that apply to one category.

        The category set is a JSON array, and an empty array means "every
        category", so membership is decided in Python after a narrow fetch of
        active rows rather than with a JSON containment query that could not
        express the empty-means-all rule.
        """
        templates = await self.list_all(active_only=True)
        return [t for t in templates if t.applies_to(category)]

    async def add(self, template: Template, *, created_by: int | None = None) -> None:
        self._session.add(template_to_row(template, created_by=created_by))
        await self._session.flush()

    async def update(self, template: Template) -> None:
        row = await self._session.get(ReplyTemplateModel, template.id)
        if row is None:
            raise NotFoundError("Template not found.", template_id=template.id)
        template_apply(row, template)
        await self._session.flush()


__all__ = [
    "OPEN_STATES",
    "SqlAlchemyTemplateRepository",
    "SqlAlchemyTicketRepository",
]
