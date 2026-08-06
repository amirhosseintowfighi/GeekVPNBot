"""Notification error taxonomy.

Suppression is deliberately NOT an error -- it is a recorded outcome. The
errors here are genuine misuse: an empty broadcast body, editing a broadcast
that is already half sent, an unknown template key.
"""

from __future__ import annotations

from geekvpn.domain.base.errors import (
    ConflictError,
    NotFoundError,
    ValidationError,
)


class NotificationError(ValidationError):
    code = "notification_error"
    message = "\u062e\u0637\u0627 \u062f\u0631 \u0633\u0627\u0645\u0627\u0646\u0647\u0654 \u0627\u0637\u0644\u0627\u0639\u200c\u0631\u0633\u0627\u0646\u06cc."


class NotificationNotFound(NotFoundError):
    code = "notification_not_found"
    message = (
        "\u0627\u0637\u0644\u0627\u0639\u06cc\u0647 \u06cc\u0627\u0641\u062a \u0646\u0634\u062f."
    )

    def __init__(self, notification_id: str) -> None:
        super().__init__(
            f"Notification {notification_id!r} was not found.",
            notification_id=notification_id,
        )


class BroadcastNotFound(NotFoundError):
    code = "broadcast_not_found"
    message = "\u067e\u06cc\u0627\u0645 \u0647\u0645\u06af\u0627\u0646\u06cc \u06cc\u0627\u0641\u062a \u0646\u0634\u062f."

    def __init__(self, broadcast_id: str) -> None:
        super().__init__(
            f"Broadcast {broadcast_id!r} was not found.",
            broadcast_id=broadcast_id,
        )


class TemplateNotFound(NotFoundError):
    """A notification was requested for a key with no Persian copy.

    Fails loudly rather than sending an empty message: a blank Telegram push
    is worse than a missing one.
    """

    code = "notification_template_not_found"
    message = "\u0645\u062a\u0646 \u0627\u06cc\u0646 \u0627\u0637\u0644\u0627\u0639\u06cc\u0647 \u062a\u0639\u0631\u06cc\u0641 \u0646\u0634\u062f\u0647 \u0627\u0633\u062a."

    def __init__(self, key: str) -> None:
        super().__init__(f"No Persian template registered for {key!r}.", key=key)


class MissingTemplateField(NotificationError):
    """The caller did not supply a placeholder the Persian copy requires."""

    code = "missing_template_field"
    message = "\u0627\u0637\u0644\u0627\u0639\u0627\u062a \u0644\u0627\u0632\u0645 \u0628\u0631\u0627\u06cc \u0645\u062a\u0646 \u0627\u0637\u0644\u0627\u0639\u06cc\u0647 \u06a9\u0627\u0645\u0644 \u0646\u06cc\u0633\u062a."

    def __init__(self, *, key: str, field: str) -> None:
        super().__init__(
            f"Template {key!r} requires field {field!r}.",
            key=key,
            field=field,
        )


class BroadcastNotEditable(ConflictError):
    """Raised when editing a broadcast that has begun sending.

    Half the audience already has the old copy; changing it now would mean two
    different messages went out under one name.
    """

    code = "broadcast_not_editable"
    message = "\u0627\u06cc\u0646 \u067e\u06cc\u0627\u0645 \u062f\u06cc\u06af\u0631 \u0642\u0627\u0628\u0644 \u0648\u06cc\u0631\u0627\u06cc\u0634 \u0646\u06cc\u0633\u062a."

    def __init__(self, *, broadcast_id: str, state: str) -> None:
        super().__init__(
            f"Broadcast {broadcast_id!r} is {state!r} and can no longer be edited.",
            broadcast_id=broadcast_id,
            state=state,
        )


class IllegalBroadcastTransition(ConflictError):
    code = "illegal_broadcast_transition"
    message = "\u0627\u06cc\u0646 \u062a\u063a\u06cc\u06cc\u0631 \u0648\u0636\u0639\u06cc\u062a \u0645\u062c\u0627\u0632 \u0646\u06cc\u0633\u062a."

    def __init__(self, *, current: str, target: str) -> None:
        super().__init__(
            f"A broadcast in state {current!r} cannot move to {target!r}.",
            current=current,
            target=target,
        )


class EmptyAudience(NotificationError):
    """Sending to nobody is almost always a targeting mistake."""

    code = "empty_audience"
    message = "\u0645\u062e\u0627\u0637\u0628\u06cc \u0628\u0631\u0627\u06cc \u0627\u06cc\u0646 \u067e\u06cc\u0627\u0645 \u067e\u06cc\u062f\u0627 \u0646\u0634\u062f."


__all__ = [
    "BroadcastNotEditable",
    "BroadcastNotFound",
    "EmptyAudience",
    "IllegalBroadcastTransition",
    "MissingTemplateField",
    "NotificationError",
    "NotificationNotFound",
    "TemplateNotFound",
]
