"""The bot's "sign in to the app with a username" screens (profile)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.presentation.bot.handlers import app_login
from geekvpn.presentation.bot.states import Profile
from geekvpn.presentation.bot.ui import text as T
from tests.unit.bot.test_app_login_handler import _Query
from tests.unit.identity.test_app_password_login import PasswordWorld

pytestmark = pytest.mark.unit


class _State:
    def __init__(self) -> None:
        self.state: Any = None
        self.data: dict[str, Any] = {}

    async def set_state(self, state: Any) -> None:
        self.state = state

    async def update_data(self, **values: Any) -> None:
        self.data.update(values)

    async def get_data(self) -> dict[str, Any]:
        return dict(self.data)

    async def clear(self) -> None:
        self.state = None
        self.data = {}


class _Typed:
    """A message the customer typed; remembers whether the bot deleted it."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.deleted = False
        self.replies: list[str] = []

    async def delete(self) -> None:
        self.deleted = True

    async def answer(self, text: str, **_: Any) -> None:
        self.replies.append(text)


async def _world() -> tuple[PasswordWorld, Any, SimpleNamespace]:
    world = PasswordWorld()
    user = await world.customer()
    scope = SimpleNamespace(app_password_login=world.password_login, reseller=None)
    return world, user, scope


async def test_choosing_a_username_then_a_password_stores_them_and_deletes_the_password() -> None:
    world, user, scope = await _world()
    state = _State()

    await app_login.on_password_set(_Query(), state, scope=scope)  # type: ignore[arg-type]
    assert state.state == Profile.app_username

    await app_login.on_app_username(_Typed("Ali_92"), state, scope=scope, user=user)  # type: ignore[arg-type]
    assert state.state == Profile.app_password

    typed = _Typed("correct horse")
    await app_login.on_app_password(typed, state, scope=scope, user=user)  # type: ignore[arg-type]

    assert typed.deleted
    assert state.state is None
    assert world.credentials.items[user.id].username == "ali_92"
    assert "ali_92" in typed.replies[-1]
    assert "correct horse" not in "".join(typed.replies)


async def test_an_invalid_or_taken_username_asks_again() -> None:
    world, user, scope = await _world()
    other = await world.customer(telegram_id=2)
    await world.password_login.set_credentials(other.id, username="taken_1", password="x" * 12)
    state = _State()
    await state.set_state(Profile.app_username)

    bad = _Typed("1bad")
    await app_login.on_app_username(bad, state, scope=scope, user=user)  # type: ignore[arg-type]
    taken = _Typed("taken_1")
    await app_login.on_app_username(taken, state, scope=scope, user=user)  # type: ignore[arg-type]

    assert bad.replies == [T.APP_CREDS_USERNAME_INVALID]
    assert taken.replies == [T.APP_CREDS_USERNAME_TAKEN]
    assert state.state == Profile.app_username


async def test_a_short_password_is_deleted_and_asked_for_again() -> None:
    world, user, scope = await _world()
    state = _State()
    await state.set_state(Profile.app_password)
    await state.update_data(app_username="ali_92")

    typed = _Typed("short")
    await app_login.on_app_password(typed, state, scope=scope, user=user)  # type: ignore[arg-type]

    assert typed.deleted
    assert typed.replies == [T.APP_CREDS_TOO_SHORT]
    assert state.state == Profile.app_password
    assert user.id not in world.credentials.items


async def test_removing_asks_first_then_clears_the_login() -> None:
    world, user, scope = await _world()
    await world.password_login.set_credentials(user.id, username="ali_92", password="x" * 12)

    await app_login.on_password_remove(_Query())  # type: ignore[arg-type]
    assert user.id in world.credentials.items

    confirm = _Query()
    await app_login.on_password_remove_ok(confirm, scope=scope, user=user)  # type: ignore[arg-type]
    assert user.id not in world.credentials.items
    assert confirm.toasts == [T.APP_CREDS_REMOVED]


async def test_a_resellers_bot_does_not_offer_the_app_password() -> None:
    _, _user, scope = await _world()
    scope.reseller = SimpleNamespace(id="shop")
    state = _State()

    await app_login.on_password_set(_Query(), state, scope=scope)  # type: ignore[arg-type]

    assert state.state is None


def test_the_menu_offers_setting_when_there_is_no_login_and_changing_when_there_is() -> None:
    body, markup = app_login._password_menu(None)
    assert body == T.APP_CREDS_INTRO
    assert markup.inline_keyboard[0][0].text == T.BTN_APP_CREDS_SET

    body, markup = app_login._password_menu("ali_92")
    assert "ali_92" in body
    labels = [row[0].text for row in markup.inline_keyboard]
    assert T.BTN_APP_CREDS_CHANGE in labels and T.BTN_APP_CREDS_REMOVE in labels
