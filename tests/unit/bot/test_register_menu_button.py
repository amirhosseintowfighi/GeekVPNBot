"""The menu button is the only door into the Mini App.

Nothing in the bot renders a WebApp button, so a customer reaches the Mini App
through Telegram's own menu button and nowhere else. While the bot never set
it, that button held whatever URL had been typed into BotFather by hand - in
production a path on the API host, which answers a Mini App with 404 JSON.
"""

from __future__ import annotations

import pytest
from aiogram.types import MenuButtonWebApp

from geekvpn.infrastructure.config.settings import Settings, get_settings
from geekvpn.presentation.bot.app import register_menu_button
from geekvpn.presentation.bot.ui import text

pytestmark = pytest.mark.unit

MINI_APP = "https://app.example.com"


@pytest.fixture
def settings_with_mini_app(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> Settings:
    monkeypatch.setenv("TELEGRAM__MINI_APP_URL", MINI_APP)
    get_settings.cache_clear()
    return get_settings()


class AcceptingBot:
    def __init__(self) -> None:
        self.menu_button: MenuButtonWebApp | None = None

    async def set_chat_menu_button(self, *, menu_button: MenuButtonWebApp) -> bool:
        self.menu_button = menu_button
        return True


class RejectingBot:
    def __init__(self) -> None:
        self.calls = 0

    async def set_chat_menu_button(self, *, menu_button: MenuButtonWebApp) -> bool:
        self.calls += 1
        raise ConnectionError("Cannot connect to host api.telegram.org")


@pytest.mark.asyncio
async def test_the_button_opens_the_configured_mini_app(settings_with_mini_app: Settings) -> None:
    bot = AcceptingBot()

    registered = await register_menu_button(bot, settings_with_mini_app)

    assert registered is True
    assert bot.menu_button is not None
    assert bot.menu_button.web_app.url == MINI_APP
    assert bot.menu_button.text == text.MENU_BUTTON_MINI_APP


@pytest.mark.asyncio
async def test_an_unset_url_leaves_the_existing_button_alone(settings: Settings) -> None:
    """Better a stale button than one pointed at the empty string, which
    Telegram would reject and which would strip whatever was working."""
    bot = AcceptingBot()

    registered = await register_menu_button(bot, settings)

    assert registered is False
    assert bot.menu_button is None


@pytest.mark.asyncio
async def test_telegram_being_unreachable_does_not_take_the_bot_down(
    settings_with_mini_app: Settings,
) -> None:
    bot = RejectingBot()

    registered = await register_menu_button(bot, settings_with_mini_app)

    assert registered is False
    assert bot.calls == 1
