"""The main bot's own wording, edited from inside the bot, and the rules."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.application.platform.settings_service import RULES_ENABLED, TEXT_OVERRIDES
from geekvpn.domain.identity.permissions import Permission
from geekvpn.presentation.bot.handlers import admin_texts, rules
from geekvpn.presentation.bot.handlers.menu import home_keyboard
from geekvpn.presentation.bot.ui import admin_text as A
from geekvpn.presentation.bot.ui import copy as C
from geekvpn.presentation.bot.ui import text as T
from tests.unit.bot.test_app_password_handler import _State, _Typed

pytestmark = pytest.mark.unit


def test_a_resellers_words_win_then_the_main_bots_then_ours() -> None:
    both = SimpleNamespace(reseller_texts={"RULES": "shop"}, platform_texts={"RULES": "main"})
    main_only = SimpleNamespace(reseller_texts={}, platform_texts={"RULES": "main"})
    neither = SimpleNamespace(reseller_texts=None, platform_texts=None)

    assert C.resolve(both, "RULES") == "shop"
    assert C.resolve(main_only, "RULES") == "main"
    assert C.resolve(neither, "RULES") == T.RULES


class Settings:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {TEXT_OVERRIDES.key: {}, RULES_ENABLED.key: False}

    async def get(self, definition: Any) -> Any:
        return self.values[definition.key]

    async def set(self, key: str, value: Any, **_: Any) -> None:
        self.values[key] = value


class Session:
    async def commit(self) -> None:
        return None


def editor_scope(monkeypatch: pytest.MonkeyPatch) -> Any:
    admin = SimpleNamespace(
        id=uuid.uuid4(),
        username="boss",
        has_permission=lambda permission: permission is Permission.SETTINGS_WRITE,
    )

    async def guard(scope: Any, user: Any) -> Any:
        return admin

    monkeypatch.setattr(admin_texts, "_guard", guard)
    return SimpleNamespace(settings_service=Settings(), session=Session())


async def test_a_text_that_drops_a_placeholder_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = editor_scope(monkeypatch)
    state = _State()
    await state.update_data(text_key="WELCOME_NEW")
    typed = _Typed("سلام به فروشگاه ما")

    await admin_texts.on_text_written(typed, state, scope=scope, user=object())  # type: ignore[arg-type]

    assert "{name}" in typed.replies[-1] or "{brand}" in typed.replies[-1]
    assert scope.settings_service.values[TEXT_OVERRIDES.key] == {}


async def test_a_text_that_keeps_them_is_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    scope = editor_scope(monkeypatch)
    state = _State()
    await state.update_data(text_key="RULES")
    typed = _Typed("قانون تازه")

    await admin_texts.on_text_written(typed, state, scope=scope, user=object())  # type: ignore[arg-type]

    assert typed.replies[-1] == A.TEXT_SAVED
    assert scope.settings_service.values[TEXT_OVERRIDES.key] == {"RULES": "قانون تازه"}


def test_the_rules_are_hidden_until_switched_on() -> None:
    def labels(markup: Any) -> list[str]:
        return [button.text for row in markup.inline_keyboard for button in row]

    assert not any(T.MENU_RULES in label for label in labels(home_keyboard()))
    assert any(T.MENU_RULES in label for label in labels(home_keyboard(rules=True)))


async def test_rules_answer_only_when_switched_on() -> None:
    chat = _Typed("/rules")

    await rules.on_rules_command(chat, _State(), scope=SimpleNamespace(rules_enabled=False))  # type: ignore[arg-type]
    await rules.on_rules_command(
        chat,  # type: ignore[arg-type]
        _State(),  # type: ignore[arg-type]
        scope=SimpleNamespace(rules_enabled=True, reseller_texts=None, platform_texts=None),
    )

    assert chat.replies == [T.ERR_UNKNOWN_COMMAND, T.RULES]
