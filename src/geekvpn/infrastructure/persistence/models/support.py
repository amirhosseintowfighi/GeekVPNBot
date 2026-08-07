"""Support tables: tickets, messages, attachments, reply templates.

Schema decisions worth defending:

* **Internal notes live in the same table as replies.** They are the same thing
  with a different audience, and a separate table guarantees that one day a
  query forgets to union it and leaks a note to a customer, or -- worse --
  forgets to exclude it. One table, one ``kind`` column, one filter.
* **Attachments are JSONB on the message.** Telegram gives us a ``file_id``, not
  bytes. There is nothing to join to.
* **``waiting_since`` is stored, not derived.** The SLA queue sorts by it on
  every operator poll; recomputing it from the message list would be a
  correlated subquery on the hottest support read.
* **The reference is unique.** ``SUP-1405-000042`` is quoted by customers in
  Telegram; it is an external identifier, not a display nicety.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from geekvpn.domain.support.enums import (
    MessageKind,
    TicketCategory,
    TicketPriority,
    TicketState,
)
from geekvpn.infrastructure.persistence.base import Base, TimestampMixin


def _values(enum_type: type[enum.Enum]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_type)


class TicketModel(TimestampMixin, Base):
    __tablename__ = "support_tickets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    reference: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    subject_fa: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    priority: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TicketState.OPEN.value, index=True
    )

    assignee_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    #: When the clock started running against us. Null while we are waiting on
    #: the customer -- their silence is not an SLA breach.
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Denormalised for the grid; the messages table remains the truth.
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint(
            f"category IN ({_values(TicketCategory)})", name="support_tickets_category"
        ),
        CheckConstraint(
            f"priority IN ({_values(TicketPriority)})", name="support_tickets_priority"
        ),
        CheckConstraint(f"state IN ({_values(TicketState)})", name="support_tickets_state"),
        # The operator queue: open work, most overdue first.
        Index("ix_support_tickets_state_waiting", "state", "waiting_since"),
        Index("ix_support_tickets_user_state", "user_id", "state"),
    )


class TicketMessageModel(TimestampMixin, Base):
    __tablename__ = "support_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ticket_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("support_tickets.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    body_fa: Mapped[str] = mapped_column(Text, nullable=False)
    #: Null for system-generated status changes. Nobody wrote them.
    author_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    template_id: Mapped[str | None] = mapped_column(String(64), index=True)
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (
        CheckConstraint(f"kind IN ({_values(MessageKind)})", name="support_messages_kind"),
        Index("ix_support_messages_ticket_sent", "ticket_id", "sent_at"),
    )


class ReplyTemplateModel(TimestampMixin, Base):
    __tablename__ = "support_templates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title_fa: Mapped[str] = mapped_column(String(128), nullable=False)
    body_fa: Mapped[str] = mapped_column(Text, nullable=False)
    #: Which ticket categories this template is offered for. A template that
    #: fits both "payment" and "account" is normal, so this is a list, not a
    #: single column: the aggregate holds a set and a scalar column could not
    #: round-trip it.
    #:
    #: An empty list means "offer this for every category".
    categories: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    use_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[int | None] = mapped_column(BigInteger)

    __table_args__ = (
        # A CHECK cannot validate the members of a JSON array without a
        # subquery, so category membership is enforced by the mapper, which
        # parses every value through the TicketCategory enum on load.
        Index("ix_support_templates_active", "active"),
    )
