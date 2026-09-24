"""`/start applogin_<code>` in the bot, and the approve / cancel buttons."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from aiogram.filters import CommandObject

from geekvpn.domain.identity.app_login import AppLoginStatus
from geekvpn.presentation.bot.handlers import app_login
from geekvpn.presentation.bot.handlers.start import on_start
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import AppLoginCB
from tests.unit.identity.test_app_link_login import OWNER, STRANGER, World

pytestmark = pytest.mark.unit


class _Chat:
    """Records what the bot said."""

    def __init__(self) -> None:
        self.said: list[tuple[str, Any]] = []
        self.chat = SimpleNamespace(id=OWNER)

    async def answer(self, text: str, **kwargs: Any) -> None:
        self.said.append((text, kwargs.get("reply_markup")))


class _State:
    async def clear(self) -> None: ...


class _Query:
    def __init__(self) -> None:
        self.toasts: list[str | None] = []
        # Not an aiogram Message, so `safe_edit` leaves it alone.
        self.message = None

    async def answer(self, text: str | None = None, show_alert: bool = False) -> None:
        self.toasts.append(text)


def _scope(world: World, *, reseller: Any = None) -> SimpleNamespace:
    return SimpleNamespace(app_link_login=world.login, reseller=reseller)


def _user(telegram_id: int) -> SimpleNamespace:
    return SimpleNamespace(telegram_id=telegram_id, id=None)


async def _start(chat: _Chat, *, scope: Any, user: Any, payload: str) -> None:
    await on_start(
        chat,  # type: ignore[arg-type]
        _State(),  # type: ignore[arg-type]
        services=None,  # type: ignore[arg-type]
        scope=scope,
        user=user,
        command=CommandObject(prefix="/", command="start", args=payload),
    )


async def test_the_link_asks_its_opener_to_approve_the_named_device() -> None:
    world = World()
    started = await world.start()
    chat = _Chat()

    await _start(chat, scope=_scope(world), user=_user(OWNER), payload=f"applogin_{started.code}")

    [(text, markup)] = chat.said
    assert "Pixel 6" in text
    assert "GeekVPN" in text
    buttons = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert AppLoginCB(rid=started.request_id.hex, act="ok").pack() in buttons
    assert AppLoginCB(rid=started.request_id.hex, act="no").pack() in buttons
    assert world.requests.items[started.request_id].telegram_user_id == OWNER


async def test_a_reused_link_is_refused_in_plain_words() -> None:
    world = World()
    started = await world.start()
    await _start(
        _Chat(), scope=_scope(world), user=_user(OWNER), payload=f"applogin_{started.code}"
    )
    chat = _Chat()

    await _start(
        chat, scope=_scope(world), user=_user(STRANGER), payload=f"applogin_{started.code}"
    )

    assert chat.said == [(T.APP_LOGIN_USED, None)]


async def test_a_resellers_bot_does_not_sign_the_app_in() -> None:
    world = World()
    started = await world.start()
    chat = _Chat()

    await _start(
        chat,
        scope=_scope(world, reseller=SimpleNamespace(id="shop")),
        user=_user(OWNER),
        payload=f"applogin_{started.code}",
    )

    assert chat.said == [(T.APP_LOGIN_WRONG_BOT, None)]
    assert world.requests.items[started.request_id].telegram_user_id is None


async def test_approve_moves_the_request_on_and_a_stranger_cannot_press_it() -> None:
    world = World()
    started = await world.start()
    await _start(
        _Chat(), scope=_scope(world), user=_user(OWNER), payload=f"applogin_{started.code}"
    )
    approve = AppLoginCB(rid=started.request_id.hex, act="ok")

    stranger = _Query()
    await app_login.on_decision(
        stranger,  # type: ignore[arg-type]
        approve,
        scope=_scope(world),
        user=_user(STRANGER),
    )
    assert stranger.toasts == [T.APP_LOGIN_NOT_YOURS]
    assert world.requests.items[started.request_id].status is AppLoginStatus.PENDING

    owner = _Query()
    await app_login.on_decision(
        owner,  # type: ignore[arg-type]
        approve,
        scope=_scope(world),
        user=_user(OWNER),
    )
    assert world.requests.items[started.request_id].status is AppLoginStatus.APPROVED
