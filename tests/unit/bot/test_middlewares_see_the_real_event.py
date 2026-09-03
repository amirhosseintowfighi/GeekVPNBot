"""An outer middleware is handed an `Update`, not the message inside it.

Two middlewares were written as though it were the inner object, and both
failed silently in the direction that looks like nothing is wrong:

* `ThrottlingMiddleware` matched neither `Message` nor `CallbackQuery`, fell
  through on every update, and has therefore never rate-limited anybody - the
  only symptom being Telegram throttling *us* for reasons nobody connected to
  it;
* `ChannelGateMiddleware` drew nothing and returned `None`, so a customer who
  had not joined pressed /start and the bot went completely quiet.

The first test here feeds a real `Update` through a real `Dispatcher` rather
than asserting on what we believe aiogram does. That is the whole point: this
class of bug comes from being confident about a framework's behaviour without
checking it, and a test that encodes the same assumption would have passed
happily beside the broken code.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Dispatcher, Router
from aiogram.types import CallbackQuery, Chat, Message, TelegramObject, Update, User

from geekvpn.presentation.bot.events import inner_event

pytestmark = pytest.mark.unit


def _message() -> Message:
    return Message(
        message_id=1,
        date=datetime.now(UTC),
        chat=Chat(id=1, type="private"),
        from_user=User(id=1, is_bot=False, first_name="A"),
        text="/start",
    )


class _Bot:
    id = 1

    async def __call__(self, *args: Any, **kwargs: Any) -> None:
        return None


def test_an_outer_middleware_really_is_handed_an_update():
    """Checked against aiogram itself, not against our belief about it."""
    seen: list[str] = []

    dispatcher = Dispatcher()
    router = Router()

    @dispatcher.update.outer_middleware()
    async def spy(handler, event, data):  # type: ignore[no-untyped-def]
        seen.append(type(event).__name__)
        return await handler(event, data)

    @router.message()
    async def on_message(message: Message) -> None:
        seen.append(f"handler:{type(message).__name__}")

    dispatcher.include_router(router)
    asyncio.run(dispatcher.feed_update(_Bot(), Update(update_id=1, message=_message())))

    assert seen == ["Update", "handler:Message"]


def test_the_message_is_recovered_from_the_update():
    update = Update(update_id=1, message=_message())

    assert inner_event(update) is update.message


def test_a_callback_is_recovered_too():
    query = CallbackQuery(
        id="1",
        from_user=User(id=1, is_bot=False, first_name="A"),
        chat_instance="x",
        data="gate:recheck",
        message=_message(),
    )
    update = Update(update_id=1, callback_query=query)

    assert inner_event(update) is query


def test_an_already_unwrapped_event_passes_through():
    """So a middleware does not have to know which observer it was registered
    on - which is exactly the knowledge that was wrong."""
    message = _message()

    assert inner_event(message) is message


def test_an_update_carrying_neither_yields_nothing():
    """A poll answer, a chat member change. No middleware here has anything to
    say about those, and they must pass through untouched rather than being
    mistaken for something to act on."""

    class Other(TelegramObject):
        pass

    assert inner_event(Update(update_id=1)) is None
    assert inner_event(Other()) is None
