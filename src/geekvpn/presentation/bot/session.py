"""The HTTP session every `Bot` in the bot service is built on."""

from __future__ import annotations

from aiogram.client.session.aiohttp import AiohttpSession

from geekvpn.infrastructure.outbound_proxy import TELEGRAM_API, proxy_for


def telegram_session() -> AiohttpSession | None:
    """A session through the SOCKS5 proxy when one is configured.

    `None` lets aiogram build its default, direct session. Every `Bot` the
    service makes - ours and each reseller's - goes through this, so a server
    that can only reach Telegram through the proxy has no bot that forgets to.
    """
    proxy = proxy_for(TELEGRAM_API)
    return AiohttpSession(proxy=proxy) if proxy else None


__all__ = ["telegram_session"]
