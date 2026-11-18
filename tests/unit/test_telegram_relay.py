"""The Bot API can be reached through a relay instead of a proxy.

From a server in Iran neither api.telegram.org nor any proxy the operator
could find answered: every Bot API call read-timed out. A Cloudflare Worker on
their own domain does get through. `TELEGRAM__API_BASE_URL` points every Bot
API call - aiogram's, the notification sender's, the token check's, Stars',
the receipt download's - at it, and requests to it go direct, not through the
proxy that was failing.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from geekvpn.infrastructure import outbound_proxy
from geekvpn.infrastructure.notifications.telegram import HttpTelegramSender
from geekvpn.infrastructure.outbound_proxy import (
    ProxyPolicy,
    install_proxy,
    install_telegram_api,
    telegram_api_base,
)
from geekvpn.presentation.bot.session import telegram_session

pytestmark = pytest.mark.unit

RELAY = "https://tg.example.com"


@pytest.fixture(autouse=True)
def _restore() -> Iterator[None]:
    yield
    install_telegram_api("")
    install_proxy(ProxyPolicy())


def test_without_a_relay_the_api_is_telegrams_own() -> None:
    install_telegram_api("")
    assert telegram_api_base() == "https://api.telegram.org"


def test_a_relay_is_used_with_its_trailing_slash_dropped() -> None:
    install_telegram_api(RELAY + "/")
    assert telegram_api_base() == RELAY


def test_notifications_go_to_the_relay_and_not_through_the_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_proxy(ProxyPolicy.build("socks5://dead.proxy:1080"))
    install_telegram_api(RELAY)
    seen: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        seen["url"] = url
        seen["proxy"] = kwargs.get("proxy")
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "post", fake_post)
    HttpTelegramSender("123:abc").send_message(chat_id=1, text="x")

    assert seen["url"] == f"{RELAY}/bot123:abc/sendMessage"
    assert seen["proxy"] is None


async def test_the_bots_talk_to_the_relay() -> None:
    install_telegram_api(RELAY)
    session = telegram_session()
    assert session is not None
    assert session.api.api_url(token="123:abc", method="getMe") == f"{RELAY}/bot123:abc/getMe"
    assert session.proxy is None
    await session.close()


async def test_with_neither_relay_nor_proxy_aiogram_keeps_its_default() -> None:
    install_telegram_api("")
    assert telegram_session() is None
    assert outbound_proxy.proxy_for("https://api.telegram.org") is None
