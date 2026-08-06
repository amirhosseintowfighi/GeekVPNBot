"""The two concrete channels."""

from __future__ import annotations

from geekvpn.application.notifications.channels import InboxChannel, TelegramChannel
from geekvpn.domain.notifications.enums import (
    NotificationChannel,
    SuppressionReason,
)
from geekvpn.domain.notifications.message import render
from tests.unit.notifications.fakes import USER_ID, FakeChatIds, FakeTelegramSender

MESSAGE = render("expiry.today", plan="Geek Turbo")


def test_inbox_channel_always_succeeds():
    """The saved aggregate is the inbox, so there is nothing to fail."""
    channel = InboxChannel()
    assert channel.channel is NotificationChannel.MINIAPP
    result = channel.deliver(user_id=USER_ID, message=MESSAGE, notification_id="ntf-1")
    assert result.ok


def test_telegram_channel_sends_the_html_body():
    sender = FakeTelegramSender()
    channel = TelegramChannel(sender=sender, chat_ids=FakeChatIds())
    result = channel.deliver(user_id=USER_ID, message=MESSAGE, notification_id="ntf-1")
    assert result.ok
    chat_id, text = sender.sent[0]
    assert chat_id == 555
    assert text.startswith("<b>")


def test_user_without_a_chat_id_is_refused_not_failed():
    """Signing up through the Mini App is normal, not an error."""
    channel = TelegramChannel(sender=FakeTelegramSender(), chat_ids=FakeChatIds(mapping={}))
    result = channel.deliver(user_id=USER_ID, message=MESSAGE, notification_id="ntf-1")
    assert not result.ok
    assert result.suppressed is SuppressionReason.NO_CHAT_ID


def test_a_blocked_bot_is_suppression_not_a_retryable_failure():
    sender = FakeTelegramSender(raises=RuntimeError("Forbidden: bot was blocked by the user"))
    channel = TelegramChannel(sender=sender, chat_ids=FakeChatIds())
    result = channel.deliver(user_id=USER_ID, message=MESSAGE, notification_id="ntf-1")
    assert result.suppressed is SuppressionReason.BLOCKED


def test_a_transient_error_is_a_failure_worth_retrying():
    sender = FakeTelegramSender(raises=TimeoutError("read timeout"))
    channel = TelegramChannel(sender=sender, chat_ids=FakeChatIds())
    result = channel.deliver(user_id=USER_ID, message=MESSAGE, notification_id="ntf-1")
    assert not result.ok
    assert result.suppressed is None
    assert result.error == "TimeoutError"
