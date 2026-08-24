"""Notifications must actually leave the building.

`TelegramChannel` was written, tested, and never constructed by anything. The
scope registered the in-app inbox alone, so every notification the platform has
ever produced - broadcasts, expiry reminders, payment confirmations - was
written to a table the customer can only see by opening the Mini App. The
broadcast history said "sent 2/2" and two phones stayed silent.
"""

from __future__ import annotations

import httpx
import pytest

from geekvpn.application.notifications.channels import TelegramChannel
from geekvpn.domain.notifications.enums import NotificationCategory, SuppressionReason
from geekvpn.domain.notifications.message import RenderedMessage
from geekvpn.infrastructure.notifications.telegram import (
    HttpTelegramSender,
    TelegramApiError,
    TelegramIdIsTheUserId,
)

pytestmark = pytest.mark.unit

MESSAGE = RenderedMessage(
    key="broadcast",
    category=NotificationCategory.NEWS,
    title_fa="عنوان",
    body_fa="متن پیام",
)


class RecordingSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[dict[str, object]] = []
        self._error = error

    def send_message(self, *, chat_id: int, text: str, action: str | None = None) -> None:
        self.calls.append({"chat_id": chat_id, "text": text, "action": action})
        if self._error is not None:
            raise self._error


def test_the_user_id_is_the_chat_id() -> None:
    """Every integer id in the synchronous half is already a Telegram id."""
    assert TelegramIdIsTheUserId().telegram_id(87791922) == 87791922


def test_a_message_reaches_the_sender_with_the_recipients_chat_id() -> None:
    sender = RecordingSender()
    channel = TelegramChannel(sender=sender, chat_ids=TelegramIdIsTheUserId())

    result = channel.deliver(user_id=87791922, message=MESSAGE, notification_id="n1")

    assert result.ok is True
    assert sender.calls[0]["chat_id"] == 87791922
    assert "متن پیام" in str(sender.calls[0]["text"])


def test_a_customer_who_blocked_the_bot_is_suppressed_not_retried() -> None:
    """Retrying somebody who left is how a bot gets reported."""
    sender = RecordingSender(TelegramApiError("Forbidden: bot was blocked by the user"))
    channel = TelegramChannel(sender=sender, chat_ids=TelegramIdIsTheUserId())

    result = channel.deliver(user_id=1, message=MESSAGE, notification_id="n1")

    assert result.suppressed is SuppressionReason.BLOCKED


def test_a_transport_failure_is_a_failure_not_a_suppression() -> None:
    sender = RecordingSender(httpx.ConnectError("connection refused"))
    channel = TelegramChannel(sender=sender, chat_ids=TelegramIdIsTheUserId())

    result = channel.deliver(user_id=1, message=MESSAGE, notification_id="n1")

    assert result.ok is False
    assert result.suppressed is None


def test_the_sender_posts_to_the_bot_api(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        seen["url"] = url
        seen["json"] = kwargs.get("json")
        return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)

    HttpTelegramSender("123:ABC").send_message(chat_id=42, text="سلام")

    assert seen["url"] == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert isinstance(seen["json"], dict)
    assert seen["json"]["chat_id"] == 42


def test_the_api_description_survives_for_the_channel_to_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The channel classifies on this text; losing it loses the distinction."""

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(
            403,
            json={"ok": False, "description": "Forbidden: bot was blocked by the user"},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    with pytest.raises(TelegramApiError, match="bot was blocked"):
        HttpTelegramSender("123:ABC").send_message(chat_id=42, text="سلام")
