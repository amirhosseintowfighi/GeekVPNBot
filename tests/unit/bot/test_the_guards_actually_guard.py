"""The two guards do something, driven through a real dispatcher.

Both were inert. `test_middlewares_see_the_real_event` explains why; this asks
the only question that matters afterwards - does the handler still run when it
should not.

Driven end to end rather than by calling `__call__` directly, because calling
it directly is what would let somebody hand it a `Message` and watch it pass.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Dispatcher, Router
from aiogram.types import Chat, Message, Update, User

from geekvpn.presentation.bot.channel_gate import ChannelGateMiddleware
from geekvpn.presentation.bot.throttle import ThrottlingMiddleware

pytestmark = pytest.mark.unit


class _Bot:
    id = 1

    def __init__(self, joined: bool = True) -> None:
        self.joined = joined
        self.sent: list[str] = []

    async def __call__(self, method: Any = None, *args: Any, **kwargs: Any) -> None:
        # Every outgoing call goes through here, which is how "the gate stopped
        # the handler" is told apart from "the gate stopped the handler and
        # said nothing" - the second was the actual bug, and blocking alone
        # looks identical to it.
        self.sent.append(type(method).__name__)
        return None

    async def get_chat_member(self, *, chat_id: str, user_id: int) -> Any:
        return type("M", (), {"status": "member" if self.joined else "left"})()


def _update(update_id: int, text: str = "/start") -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(UTC),
            chat=Chat(id=1, type="private"),
            from_user=User(id=1, is_bot=False, first_name="A"),
            text=text,
        ),
    )


def _dispatcher(middleware: Any, **data: Any) -> tuple[Dispatcher, list[int]]:
    handled: list[int] = []
    dispatcher = Dispatcher()
    router = Router()

    @dispatcher.update.outer_middleware()
    async def inject(handler, event, payload):  # type: ignore[no-untyped-def]
        payload.update(data)
        return await handler(event, payload)

    dispatcher.update.outer_middleware(middleware)

    @router.message()
    async def on_message(message: Message) -> None:
        handled.append(message.message_id)

    dispatcher.include_router(router)
    return dispatcher, handled


# -- throttle --------------------------------------------------------------


def test_the_throttle_lets_the_first_message_through():
    dispatcher, handled = _dispatcher(ThrottlingMiddleware())

    asyncio.run(dispatcher.feed_update(_Bot(), _update(1)))

    assert handled == [1]


def test_the_throttle_drops_the_second_one_in_the_same_instant():
    """It has never done this. Every update fell through the type check, so
    the anti-flood middleware has been decorative since it was written."""
    dispatcher, handled = _dispatcher(ThrottlingMiddleware(message_interval=5.0))
    bot = _Bot()

    asyncio.run(dispatcher.feed_update(bot, _update(1)))
    asyncio.run(dispatcher.feed_update(bot, _update(2)))

    assert handled == [1]


# -- channel gate ----------------------------------------------------------


class _Channels:
    def __init__(self, channels: list[Any]) -> None:
        self._channels = channels

    async def active(self) -> list[Any]:
        return self._channels


class _Scope:
    def __init__(self, channels: list[Any]) -> None:
        self.required_channels = _Channels(channels)


class _User:
    telegram_id = 1


def _channel() -> Any:
    from geekvpn.application.platform.channel_gate import RequiredChannel

    return RequiredChannel(id="1", chat_ref="@news", title_fa="اطلاع‌رسانی")


def test_a_joined_customer_reaches_the_handler():
    dispatcher, handled = _dispatcher(
        ChannelGateMiddleware(), scope=_Scope([_channel()]), user=_User()
    )

    asyncio.run(dispatcher.feed_update(_Bot(joined=True), _update(1)))

    assert handled == [1]


def test_a_customer_who_has_not_joined_is_stopped():
    dispatcher, handled = _dispatcher(
        ChannelGateMiddleware(), scope=_Scope([_channel()]), user=_User()
    )

    asyncio.run(dispatcher.feed_update(_Bot(joined=False), _update(1)))

    assert handled == []


def test_they_are_told_why_rather_than_met_with_silence():
    """The reported bug. Blocking the handler and drawing nothing is worse than
    not gating at all: the customer presses /start and the bot is simply mute,
    with no way to know a channel is what stands between them and it."""
    dispatcher, _ = _dispatcher(
        ChannelGateMiddleware(), scope=_Scope([_channel()]), user=_User()
    )
    bot = _Bot(joined=False)

    asyncio.run(dispatcher.feed_update(bot, _update(1)))

    assert "SendMessage" in bot.sent


def test_a_shop_with_no_channels_gates_nobody():
    dispatcher, handled = _dispatcher(
        ChannelGateMiddleware(), scope=_Scope([]), user=_User()
    )

    asyncio.run(dispatcher.feed_update(_Bot(joined=False), _update(1)))

    assert handled == [1]


# -- who the gate applies to -----------------------------------------------


class _Shop:
    def __init__(self, shop_id: str | None) -> None:
        self.id = shop_id


class _ShopScope(_Scope):
    def __init__(self, channels: list[Any], shop_id: str | None) -> None:
        super().__init__(channels)
        self.reseller = _Shop(shop_id) if shop_id else None


def test_an_existing_customer_is_gated_too():
    """Nothing in the gate asks whether the account is new. A customer who
    registered months ago and never joined is stopped the next time they touch
    the bot, not grandfathered in."""
    dispatcher, handled = _dispatcher(
        ChannelGateMiddleware(), scope=_Scope([_channel()]), user=_User()
    )

    # `is_new_user` false is what the identity middleware injects for somebody
    # who already had an account.
    asyncio.run(dispatcher.feed_update(_Bot(joined=False), _update(1, "/services")))

    assert handled == []


def test_it_applies_to_every_message_not_just_start():
    dispatcher, handled = _dispatcher(
        ChannelGateMiddleware(), scope=_Scope([_channel()]), user=_User()
    )

    asyncio.run(dispatcher.feed_update(_Bot(joined=False), _update(1, "کیف پول")))

    assert handled == []


def test_two_shops_do_not_share_a_cached_pass():
    """The same Telegram account is a separate customer in every bot. Keyed on
    the channel count alone, joining our channel let somebody straight past a
    reseller's gate for as long as the entry lived."""
    from geekvpn.presentation.bot.channel_gate import cache_key

    ours = cache_key(_ShopScope([_channel()], None), 1, [_channel()])
    theirs = cache_key(_ShopScope([_channel()], "shop-1"), 1, [_channel()])

    assert ours != theirs


def test_swapping_a_requirement_invalidates_the_pass():
    """Same count, different channel. Keyed on the count, a cached pass would
    outlive the requirement it was granted against."""
    from geekvpn.application.platform.channel_gate import RequiredChannel
    from geekvpn.presentation.bot.channel_gate import cache_key

    before = cache_key(_Scope([]), 1, [_channel()])
    after = cache_key(
        _Scope([]), 1, [RequiredChannel(id="2", chat_ref="@other", title_fa="دیگر")]
    )

    assert before != after
