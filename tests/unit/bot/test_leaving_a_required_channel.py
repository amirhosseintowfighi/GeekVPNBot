"""A customer who leaves a required channel hears from the shop, if it asked."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from aiogram.types import ChatMemberUpdated

from geekvpn.application.platform.channel_gate import RequiredChannel
from geekvpn.application.platform.settings_service import CHANNEL_LEAVE_MESSAGE_FA
from geekvpn.presentation.bot.channel_gate import ChannelGateMiddleware
from geekvpn.presentation.bot.handlers.channel_leave import on_member_change

pytestmark = pytest.mark.unit

CHANNEL = RequiredChannel(id="c1", chat_ref="@geekvpn", title_fa="کانال", invite_url=None)


def update(*, old: str, new: str, username: str = "geekvpn") -> ChatMemberUpdated:
    member = {"user": {"id": 77, "is_bot": False, "first_name": "a"}}
    return ChatMemberUpdated.model_validate(
        {
            "chat": {"id": -1001, "type": "channel", "username": username},
            "from": {"id": 77, "is_bot": False, "first_name": "a"},
            "date": 0,
            "old_chat_member": {**member, "status": old},
            "new_chat_member": {**member, "status": new},
        }
    )


class Bot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, **_: Any) -> None:
        self.sent.append((chat_id, text))


def scope(message: str) -> Any:
    async def get(definition: Any) -> Any:
        assert definition is CHANNEL_LEAVE_MESSAGE_FA
        return message

    async def active() -> list[RequiredChannel]:
        return [CHANNEL]

    return SimpleNamespace(
        settings_service=SimpleNamespace(get=get),
        required_channels=SimpleNamespace(active=active),
    )


async def test_leaving_a_required_channel_sends_the_operators_message() -> None:
    bot = Bot()

    await on_member_change(update(old="member", new="left"), bot, scope=scope("برگرد!"))

    assert bot.sent == [(77, "برگرد!")]


async def test_without_a_message_nothing_is_sent() -> None:
    bot = Bot()

    await on_member_change(update(old="member", new="left"), bot, scope=scope(""))

    assert bot.sent == []


async def test_joining_or_leaving_another_chat_says_nothing() -> None:
    bot = Bot()

    await on_member_change(update(old="left", new="member"), bot, scope=scope("x"))
    await on_member_change(
        update(old="member", new="left", username="other"), bot, scope=scope("x")
    )

    assert bot.sent == []


async def test_the_gate_lets_membership_updates_through() -> None:
    """The person leaving has, by definition, not joined - the gate would eat it."""
    reached: list[bool] = []

    async def handler(event: Any, data: Any) -> None:
        reached.append(True)

    event = SimpleNamespace(chat_member=update(old="member", new="left"))
    data = {"scope": object(), "user": SimpleNamespace(telegram_id=77), "bot": object()}
    await ChannelGateMiddleware()(handler, event, data)  # type: ignore[arg-type]

    assert reached == [True]
