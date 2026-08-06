"""Support domain errors."""

from __future__ import annotations

from geekvpn.domain.base.errors import ConflictError, NotFoundError, ValidationError


class TicketNotFound(NotFoundError):
    code = "ticket_not_found"
    message = "\u062a\u06cc\u06a9\u062a \u06cc\u0627\u0641\u062a \u0646\u0634\u062f."

    def __init__(self, ticket_id: str) -> None:
        super().__init__(f"Ticket {ticket_id!r} not found.", ticket_id=ticket_id)


class TemplateNotFound(NotFoundError):
    code = "template_not_found"
    message = "\u0642\u0627\u0644\u0628 \u067e\u06cc\u062f\u0627 \u0646\u0634\u062f."


class TicketClosed(ConflictError):
    code = "ticket_closed"
    message = (
        "\u062a\u06cc\u06a9\u062a \u0628\u0633\u062a\u0647 \u0634\u062f\u0647 \u0627\u0633\u062a."
    )

    def __init__(self, ticket_id: str) -> None:
        super().__init__(
            f"Ticket {ticket_id!r} is closed and cannot receive messages.",
            ticket_id=ticket_id,
        )


class MessageTooShort(ValidationError):
    code = "message_too_short"
    message = "\u067e\u06cc\u0627\u0645 \u062e\u06cc\u0644\u06cc \u06a9\u0648\u062a\u0627\u0647 \u0627\u0633\u062a."

    def __init__(self, *, minimum: int, actual: int) -> None:
        super().__init__(
            f"Message must be at least {minimum} characters (got {actual}).",
            minimum=minimum,
            actual=actual,
        )


class TooManyAttachments(ValidationError):
    code = "too_many_attachments"
    message = "\u062a\u0639\u062f\u0627\u062f \u067e\u06cc\u0648\u0633\u062a \u0628\u06cc\u0634 \u0627\u0632 \u062d\u062f \u0645\u062c\u0627\u0632 \u0627\u0633\u062a."


class InvalidAttachment(ValidationError):
    code = "invalid_attachment"
    message = "\u0646\u0648\u0639 \u0641\u0627\u06cc\u0644 \u067e\u06cc\u0648\u0633\u062a \u067e\u0634\u062a\u06cc\u0628\u0627\u0646\u06cc \u0646\u0645\u06cc\u200c\u0634\u0648\u062f."


__all__ = [
    "InvalidAttachment",
    "MessageTooShort",
    "TemplateNotFound",
    "TicketClosed",
    "TicketNotFound",
    "TooManyAttachments",
]
