"""The identity middleware must find the sender aiogram actually gives it."""

from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram.dispatcher.middlewares.user_context import UserContextMiddleware
from aiogram.types import Chat, Message, Update
from aiogram.types import User as TelegramUser

from geekvpn.presentation.bot.identity import _extract_user

pytestmark = pytest.mark.anyio


def _update() -> tuple[Update, TelegramUser]:
    sender = TelegramUser(id=7, is_bot=False, first_name="Ali")
    message = Message(
        message_id=1,
        date=datetime(2026, 1, 1, tzinfo=UTC),
        chat=Chat(id=7, type="private"),
        from_user=sender,
        text="/start",
    )
    return Update(update_id=1, message=message), sender


async def test_the_sender_is_found_after_aiogram_has_filled_the_handler_data() -> None:
    update, sender = _update()
    data: dict[str, Any] = {}

    async def handler(_event: Update, _data: dict[str, Any]) -> None:
        return None

    await UserContextMiddleware()(handler, update, data)

    assert _extract_user(update, data) is sender


def test_the_update_itself_carries_no_sender_attribute() -> None:
    update, _ = _update()

    assert getattr(update, "event_from_user", None) is None
