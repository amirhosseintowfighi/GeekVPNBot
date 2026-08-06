"""The two concrete channels.

``InboxChannel`` is almost empty, and that is the design rather than an
oversight: the Notification aggregate *is* the Mini App inbox row. Once the
engine has saved it, the customer can see it. So the channel's only job is to
say "yes, recorded" -- which is why the Mini App can never be the reason a
customer missed something.

``TelegramChannel`` is where the real world intrudes: a user id must be mapped
to a chat id, the bot may be blocked, and the API may rate-limit us. All three
are returned as results, never raised, so a broadcast over five thousand
people does not stop at the first person who blocked the bot.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from geekvpn.application.notifications.ports import ChannelResult
from geekvpn.domain.notifications.enums import (
    NotificationChannel,
    SuppressionReason,
)
from geekvpn.domain.notifications.message import RenderedMessage

# Substrings Telegram uses when the user is gone for good. Matching on these
# lets us record BLOCKED (never retried) instead of a generic failure (retried
# three times, pointlessly).
_PERMANENT_MARKERS = (
    "bot was blocked",
    "user is deactivated",
    "chat not found",
    "bot can't initiate",
)


@runtime_checkable
class ChatIdResolver(Protocol):
    """Maps an internal user id to a Telegram chat id.

    Returns None for a user who has never started the bot -- a normal state
    for someone who signed up through the Mini App.
    """

    def telegram_id(self, user_id: int) -> int | None: ...


@runtime_checkable
class TelegramSender(Protocol):
    """The narrow slice of the Bot API the engine needs.

    Narrow on purpose: the engine must be testable without aiogram, which is
    not installed in every environment.
    """

    def send_message(self, *, chat_id: int, text: str, action: str | None = None) -> None: ...


class InboxChannel:
    """Mini App delivery. The saved aggregate is the inbox."""

    @property
    def channel(self) -> NotificationChannel:
        return NotificationChannel.MINIAPP

    def deliver(
        self,
        *,
        user_id: int,
        message: RenderedMessage,
        notification_id: str,
    ) -> ChannelResult:
        return ChannelResult.sent()


class TelegramChannel:
    """Push delivery through the bot."""

    def __init__(self, *, sender: TelegramSender, chat_ids: ChatIdResolver) -> None:
        self._sender = sender
        self._chat_ids = chat_ids

    @property
    def channel(self) -> NotificationChannel:
        return NotificationChannel.TELEGRAM

    def deliver(
        self,
        *,
        user_id: int,
        message: RenderedMessage,
        notification_id: str,
    ) -> ChannelResult:
        try:
            chat_id = self._chat_ids.telegram_id(user_id)
        except Exception as exc:
            return ChannelResult.broke(type(exc).__name__)

        if chat_id is None:
            return ChannelResult.refused(SuppressionReason.NO_CHAT_ID)

        try:
            self._sender.send_message(
                chat_id=chat_id,
                text=message.telegram_text(),
                action=message.action,
            )
        except Exception as exc:
            text = str(exc).lower()
            if any(marker in text for marker in _PERMANENT_MARKERS):
                return ChannelResult.refused(SuppressionReason.BLOCKED)
            return ChannelResult.broke(type(exc).__name__)

        return ChannelResult.sent()


__all__ = ["ChatIdResolver", "InboxChannel", "TelegramChannel", "TelegramSender"]
