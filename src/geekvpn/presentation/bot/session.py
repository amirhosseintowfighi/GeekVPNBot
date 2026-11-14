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
    return AiohttpSession(proxy=_for_aiohttp(proxy)) if proxy else None


def _for_aiohttp(proxy: str) -> str:
    """`socks5h://` as `socks5://`, the only spelling python-socks accepts.

    `socks5h` is what curl, git and httpx call "the proxy resolves the name",
    and what `scripts/proxy.sh` writes. python-socks, under aiogram's session,
    raised on it, so the bot made no call to Telegram at all. Its `socks5`
    already leaves the name to the proxy, so nothing is lost.
    """
    if proxy.lower().startswith("socks5h://"):
        return "socks5://" + proxy[len("socks5h://") :]
    return proxy


__all__ = ["telegram_session"]
