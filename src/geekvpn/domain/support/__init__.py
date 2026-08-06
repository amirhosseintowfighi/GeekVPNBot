"""GeekVPN support bounded context."""

from __future__ import annotations

from geekvpn.domain.support.enums import (
    MessageKind,
    TicketCategory,
    TicketPriority,
    TicketState,
)
from geekvpn.domain.support.errors import (
    InvalidAttachment,
    MessageTooShort,
    TemplateNotFound,
    TicketClosed,
    TicketNotFound,
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
from geekvpn.domain.support.template import (
    MIN_BODY,
    MIN_TITLE,
    Template,
)
from geekvpn.domain.support.ticket import (
    ALLOWED_MIME_TYPES,
    MAX_ATTACHMENTS,
    MIN_MESSAGE,
    Attachment,
    Message,
    Ticket,
)

__all__ = [
    "ALLOWED_MIME_TYPES",
    "MAX_ATTACHMENTS",
    "MIN_BODY",
    "MIN_MESSAGE",
    "MIN_TITLE",
    "Attachment",
    "InvalidAttachment",
    "Message",
    "MessageKind",
    "MessageTooShort",
    "Template",
    "TemplateNotFound",
    "Ticket",
    "TicketAssigned",
    "TicketCategory",
    "TicketClosed",
    "TicketClosedEvent",
    "TicketNotFound",
    "TicketOpened",
    "TicketPriority",
    "TicketPriorityChanged",
    "TicketReplied",
    "TicketState",
    "TooManyAttachments",
]
