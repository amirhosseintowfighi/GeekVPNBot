"""Mappers between the support tables and the support aggregates.

A ticket is stored as a header row plus one row per message, and loaded back as
a single aggregate. The alternative - a JSON blob of messages on the ticket -
would make "show me every unanswered ticket, oldest first" a full table scan
and would lose the per-message read receipts the customer view depends on.

The header carries three derived columns (``message_count``, ``last_reply_at``,
``waiting_since``). They exist so the operator queue can be sorted in SQL, and
they are written from the aggregate on every save rather than trusted on load.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from geekvpn.domain.support.enums import (
    MessageKind,
    TicketCategory,
    TicketPriority,
    TicketState,
)
from geekvpn.domain.support.template import Template
from geekvpn.domain.support.ticket import Attachment, Message, Ticket
from geekvpn.infrastructure.persistence.models.support import (
    ReplyTemplateModel,
    TicketMessageModel,
    TicketModel,
)

# -- attachments -----------------------------------------------------------


def attachment_to_json(attachment: Attachment) -> dict[str, Any]:
    return {
        "file_id": attachment.file_id,
        "mime_type": attachment.mime_type,
        "size_bytes": attachment.size_bytes,
        "original_name": attachment.original_name,
    }


def attachment_from_json(raw: dict[str, Any]) -> Attachment:
    return Attachment(
        file_id=raw["file_id"],
        mime_type=raw["mime_type"],
        size_bytes=raw.get("size_bytes"),
        original_name=raw.get("original_name"),
    )


# -- messages --------------------------------------------------------------


def message_to_domain(model: TicketMessageModel) -> Message:
    return Message(
        message_id=model.id,
        ticket_id=model.ticket_id,
        kind=MessageKind(model.kind),
        body_fa=model.body_fa,
        author_id=model.author_id,
        created_at=model.sent_at,
        attachments=tuple(attachment_from_json(raw) for raw in (model.attachments or [])),
        template_id=model.template_id,
        read_at=model.read_at,
    )


def message_to_row(message: Message) -> TicketMessageModel:
    return TicketMessageModel(
        id=message.message_id,
        ticket_id=message.ticket_id,
        kind=message.kind.value,
        body_fa=message.body_fa,
        author_id=message.author_id,
        sent_at=message.created_at,
        read_at=message.read_at,
        template_id=message.template_id,
        attachments=[attachment_to_json(a) for a in message.attachments],
    )


def message_apply(model: TicketMessageModel, message: Message) -> TicketMessageModel:
    """Only the mutable parts of a message. Body and author are immutable:
    editing what a customer said would destroy the value of the transcript."""
    model.read_at = message.read_at
    return model


# -- ticket ----------------------------------------------------------------


def ticket_to_domain(model: TicketModel, *, messages: Sequence[TicketMessageModel] = ()) -> Ticket:
    ordered = sorted(messages, key=lambda row: (row.sent_at, row.id))
    return Ticket(
        model.id,
        user_id=model.user_id,
        reference=model.reference,
        category=TicketCategory(model.category),
        priority=TicketPriority(model.priority),
        subject_fa=model.subject_fa,
        state=TicketState(model.state),
        created_at=model.opened_at,
        updated_at=model.updated_at,
        assignee_id=model.assignee_id,
        messages=[message_to_domain(row) for row in ordered],
    )


def ticket_apply(model: TicketModel, ticket: Ticket) -> TicketModel:
    model.subject_fa = ticket.subject_fa
    model.category = ticket.category.value
    model.priority = ticket.priority.value
    model.state = ticket.state.value
    model.assignee_id = ticket.assignee_id
    model.opened_at = ticket.created_at
    model.last_reply_at = ticket.last_reply_at()
    model.message_count = len(ticket.messages)
    model.closed_at = ticket.updated_at if ticket.state is TicketState.CLOSED else None
    # "Waiting since" drives the overdue queue, so it must be the moment the
    # customer started waiting - not the last activity of any kind. An internal
    # note must never make a ticket look freshly attended to.
    model.waiting_since = _waiting_since(ticket)
    return model


def _waiting_since(ticket: Ticket) -> datetime | None:
    if ticket.state in (TicketState.CLOSED, TicketState.WAITING_USER):
        return None
    customer_messages = [
        message for message in ticket.messages if message.kind is MessageKind.CUSTOMER
    ]
    if not customer_messages:
        return None
    return customer_messages[-1].created_at


def ticket_to_row(ticket: Ticket) -> TicketModel:
    model = TicketModel(
        id=ticket.id,
        user_id=ticket.user_id,
        reference=ticket.reference,
    )
    return ticket_apply(model, ticket)


# -- template --------------------------------------------------------------


def template_to_domain(model: ReplyTemplateModel) -> Template:
    return Template(
        model.id,
        title_fa=model.title_fa,
        body_fa=model.body_fa,
        # Unknown values are dropped rather than raising: a category retired in
        # a later release must not make an old template unloadable.
        categories=frozenset(
            TicketCategory(value)
            for value in (model.categories or [])
            if value in set(TicketCategory)
        ),
        is_active=model.active,
        created_at=model.created_at,
        updated_at=model.updated_at,
        use_count=model.use_count,
    )


def template_apply(model: ReplyTemplateModel, template: Template) -> ReplyTemplateModel:
    model.title_fa = template.title_fa
    model.body_fa = template.body_fa
    model.categories = sorted(category.value for category in template.categories)
    model.active = template.is_active
    model.use_count = template.use_count
    return model


def template_to_row(template: Template, *, created_by: int | None = None) -> ReplyTemplateModel:
    model = ReplyTemplateModel(id=template.id, created_by=created_by)
    return template_apply(model, template)


__all__ = [
    "attachment_from_json",
    "attachment_to_json",
    "message_apply",
    "message_to_domain",
    "message_to_row",
    "template_apply",
    "template_to_domain",
    "template_to_row",
    "ticket_apply",
    "ticket_to_domain",
    "ticket_to_row",
]
