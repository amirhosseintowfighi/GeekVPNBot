"""`socks5h://` in PROXY__URL must not take the bot down.

`scripts/proxy.sh set socks5h://...` wrote that scheme to PROXY__URL, which is
what curl and git want. aiogram's session builds its connector with
python-socks, which knows `socks5` and not `socks5h`: the bot raised on its
first call to Telegram and answered nobody. For aiohttp-socks the two mean
the same thing - the proxy resolves the name - so the bot is given `socks5`.
"""

from __future__ import annotations

import pytest
from python_socks import parse_proxy_url

from geekvpn.infrastructure import outbound_proxy
from geekvpn.infrastructure.outbound_proxy import ProxyPolicy
from geekvpn.presentation.bot.session import telegram_session

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "configured",
    ["socks5h://host.docker.internal:10808", "socks5h://user:pass@host.docker.internal:10808"],
)
async def test_a_socks5h_proxy_gives_the_bot_a_session_it_can_use(
    configured: str,
) -> None:
    outbound_proxy.install_proxy(ProxyPolicy.build(configured))
    session = telegram_session()
    assert session is not None

    proxy = session.proxy
    assert isinstance(proxy, str)
    assert proxy.startswith("socks5://")
    parse_proxy_url(proxy)  # what aiogram's connector does; raised for socks5h
    await session.close()
    outbound_proxy.install_proxy(ProxyPolicy.build(""))
