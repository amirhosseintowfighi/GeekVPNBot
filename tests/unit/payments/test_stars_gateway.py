"""Telegram Stars: an invoice link from the shop's own bot, confirmed from its ledger."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import VerificationOutcome
from geekvpn.infrastructure.payments import iranian_gateways as G
from geekvpn.infrastructure.payments.stars import StarsError, StarsGateway, stars_for

pytestmark = pytest.mark.unit

PRICE = Money(250_000)


@pytest.fixture
def telegram(monkeypatch: pytest.MonkeyPatch) -> Any:
    def install(handler: Any) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        transport = httpx.MockTransport(record)

        def patched(url: str, **kwargs: Any) -> httpx.Response:
            with httpx.Client(transport=transport) as client:
                return client.post(url, **kwargs)

        monkeypatch.setattr(httpx, "post", patched)
        return seen

    return install


BOT = "123:abc"


def _gateway(token: str = BOT) -> StarsGateway:
    return StarsGateway(merchant_id="1,500", bot_token=lambda: token)


def test_the_price_of_a_star_rounds_up_never_to_nothing() -> None:
    assert stars_for(Money(3_001), 1_500) == 3
    assert stars_for(Money(1), 1_500) == 1


def test_an_unset_price_starts_nothing() -> None:
    with pytest.raises(StarsError):
        StarsGateway(merchant_id="0", bot_token=lambda: "t").begin(
            payment_id="p1", amount=PRICE, user_id=1, invoice_number="1405-1"
        )


def test_the_invoice_is_in_xtr_from_the_shops_own_bot(telegram: Any) -> None:
    seen = telegram(lambda r: httpx.Response(200, json={"ok": True, "result": "https://t.me/$abc"}))

    instruction = _gateway().begin(
        payment_id="p1", amount=PRICE, user_id=1, invoice_number="1405-1"
    )

    assert "/bot123:abc/createInvoiceLink" in str(seen[0].url)
    sent = json.loads(seen[0].content)
    assert sent["currency"] == "XTR" and sent["payload"] == "p1"
    assert sent["prices"] == [{"label": "1405-1", "amount": 167}]
    assert instruction.redirect_url == "https://t.me/$abc"
    assert instruction.metadata["gatewayReference"] == "p1:167"


def test_a_shop_without_a_bot_cannot_take_stars() -> None:
    with pytest.raises(StarsError):
        _gateway(token="").begin(payment_id="p1", amount=PRICE, user_id=1, invoice_number="x")


def _ledger(*rows: tuple[str, int]) -> Any:
    transactions = [
        {"id": f"t{i}", "amount": amount, "source": {"type": "user", "invoice_payload": payload}}
        for i, (payload, amount) in enumerate(rows)
    ]
    return lambda r: httpx.Response(
        200, json={"ok": True, "result": {"transactions": transactions}}
    )


def test_a_paid_invoice_is_found_in_the_bots_own_ledger(telegram: Any) -> None:
    telegram(_ledger(("other", 500), ("p1", 167)))

    result = _gateway().verify(payment_id="p1", reference="p1:167", expected=PRICE)

    assert result.outcome is VerificationOutcome.CONFIRMED
    assert result.amount == PRICE


def test_fewer_stars_than_asked_do_not_settle(telegram: Any) -> None:
    telegram(_ledger(("p1", 100)))

    result = _gateway().verify(payment_id="p1", reference="p1:167", expected=PRICE)

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_an_unpaid_invoice_waits_rather_than_failing(telegram: Any) -> None:
    telegram(_ledger())

    result = _gateway().verify(payment_id="p1", reference="p1:167", expected=PRICE)

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_the_registry_hands_stars_the_shops_bot() -> None:
    gateway = G.build("stars", "1500", bot_token=lambda: "999:zzz")

    assert gateway.bot_token() == "999:zzz"
