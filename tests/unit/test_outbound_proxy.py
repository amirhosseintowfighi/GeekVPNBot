"""Which calls go through the SOCKS5 proxy, and that they really do.

For a server inside Iran: Telegram and the foreign gateways only answer through
the proxy, while the Iranian bank gateways must *not* go through it - they
refuse foreign addresses, and that was a live production failure once.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from geekvpn.domain.catalog.money import Money
from geekvpn.infrastructure.outbound_proxy import ProxyPolicy, install_proxy, proxy_for

PROXY = "socks5://user:pass@10.0.0.9:1080"


@pytest.fixture(autouse=True)
def _restore_policy() -> Iterator[None]:
    yield
    install_proxy(ProxyPolicy())


def test_nothing_is_proxied_until_a_proxy_is_configured() -> None:
    assert proxy_for("https://api.telegram.org/bot1:x/getMe") is None


def test_telegram_and_the_foreign_gateways_go_through_the_proxy() -> None:
    install_proxy(ProxyPolicy.build(PROXY))

    for url in (
        "https://api.telegram.org/bot1:x/sendMessage",
        "https://api.nowpayments.io/v1/invoice",
        "https://api.plisio.net/api/v1/invoices/new",
        "https://toncenter.com/api/v2/getTransactions",
        "https://fcm.googleapis.com/v1/projects/p/messages:send",
    ):
        assert proxy_for(url) == PROXY, url


def test_iranian_gateways_and_panels_connect_directly() -> None:
    install_proxy(ProxyPolicy.build(PROXY))

    for url in (
        "https://core.isunnymoney.com/request",
        "https://payment.zarinpal.com/pg/v4/payment/request.json",
        "https://panel.doping.games:8443/api/admin/token",
    ):
        assert proxy_for(url) is None, url


def test_a_lookalike_host_is_not_mistaken_for_telegram() -> None:
    install_proxy(ProxyPolicy.build(PROXY))

    assert proxy_for("https://evilapi.telegram.org.example.com/") is None
    assert proxy_for("https://notapi.telegram.org/") is None


def test_the_operator_can_add_hosts() -> None:
    install_proxy(ProxyPolicy.build(PROXY, extra_hosts=" api.atlaspay.space , github.com"))

    assert proxy_for("https://api.atlaspay.space/api/v1/orders") == PROXY
    assert proxy_for("https://api.github.com/repos/x/y") == PROXY


def test_a_telegram_notification_is_sent_through_the_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    from geekvpn.infrastructure.notifications.telegram import HttpTelegramSender

    install_proxy(ProxyPolicy.build(PROXY))
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kwargs: Any) -> httpx.Response:
        seen.update(kwargs, url=url)
        return httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 1}},
            request=httpx.Request("POST", url),
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    HttpTelegramSender(token="1:x").send_message(chat_id=5, text="hi")

    assert seen["proxy"] == PROXY


def test_an_iranian_gateway_call_stays_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    from geekvpn.infrastructure.payments.isunnymoney import IsunnyMoneyGateway

    install_proxy(ProxyPolicy.build(PROXY))
    seen: dict[str, Any] = {}

    def fake_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
        seen.update(kwargs)
        return httpx.Response(200, json={"success": False, "message": "no"})

    monkeypatch.setattr(httpx, "request", fake_request)
    gateway = IsunnyMoneyGateway(merchant_id="m", next_order_id=lambda: 100001)
    with pytest.raises(Exception):  # noqa: B017 - only the transport matters here
        gateway.begin(
            payment_id="p",
            amount=Money(10_000),
            user_id=1,
            invoice_number="1",
            callback_url="https://shop.example/cb",
        )

    assert "proxy" in seen and seen["proxy"] is None


def test_every_bot_session_uses_the_proxy() -> None:
    from geekvpn.presentation.bot.session import telegram_session

    assert telegram_session() is None

    install_proxy(ProxyPolicy.build(PROXY))
    session = telegram_session()

    assert session is not None
    assert session.proxy == PROXY
