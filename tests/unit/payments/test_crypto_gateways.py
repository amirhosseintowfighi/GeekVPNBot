"""NowPayments, Plisio and TON: priced at the operator's rate, confirmed by asking.

What is pinned here is what costs money when wrong: the conversion (rounded
up, never to zero), a missing rate (refused, never free), and the rule that
"cannot reach them" is never "declined".
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any

import httpx
import pytest

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import VerificationOutcome
from geekvpn.infrastructure.payments import iranian_gateways as G
from geekvpn.infrastructure.payments.crypto_gateways import (
    CryptoGatewayError,
    ExchangeRates,
    NowPaymentsGateway,
    PlisioGateway,
    TonGateway,
    format_ton,
    toman_to_nanoton,
    toman_to_usd,
    ton_comment,
)

pytestmark = pytest.mark.unit

PRICE = Money(250_000)
RATES = ExchangeRates(usd_toman=100_000, ton_toman=200_000)
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> Callable[[Handler], list[httpx.Request]]:
    """Route `httpx.request` through a handler, and keep what was asked."""

    def install(handler: Handler) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        transport = httpx.MockTransport(record)

        def patched(method: str, url: str, **kwargs: Any) -> httpx.Response:
            with httpx.Client(transport=transport) as client:
                return client.request(method, url, **kwargs)

        monkeypatch.setattr(httpx, "request", patched)
        return seen

    return install


def _down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("unreachable", request=request)


# -- the arithmetic ------------------------------------------------------------


def test_dollars_are_rounded_up_to_the_cent() -> None:
    assert toman_to_usd(Money(100_001), 100_000) == Decimal("1.01")


def test_nanoton_is_rounded_up() -> None:
    assert toman_to_nanoton(Money(1), 3) == 333_333_334


@pytest.mark.parametrize("gateway", [NowPaymentsGateway, PlisioGateway, TonGateway])
def test_without_a_rate_nothing_is_started(gateway: Any, provider: Any) -> None:
    seen = provider(lambda r: httpx.Response(200, json={}))

    with pytest.raises(CryptoGatewayError):
        gateway(merchant_id="k").begin(
            payment_id="p1", amount=PRICE, user_id=1, invoice_number="1405-1"
        )
    assert seen == []


def test_every_crypto_provider_takes_the_rates_through_the_registry() -> None:
    for key in G.PRICED_IN_CRYPTO:
        gateway = G.build(key, "k", rates=lambda: RATES)
        assert gateway.rates() == RATES


# -- NowPayments ---------------------------------------------------------------


def test_nowpayments_asks_for_the_dollar_price_in_the_chosen_coin(provider: Any) -> None:
    seen = provider(
        lambda r: httpx.Response(
            201,
            json={
                "payment_id": 5524759814,
                "pay_address": "TNDFkiSmBQorNFacb3735q8MnT29sMEn4F",
                "pay_amount": 2.51,
                "pay_currency": "usdttrc20",
            },
        )
    )
    gateway = NowPaymentsGateway(merchant_id="api-key", rates=lambda: RATES)

    instruction = gateway.begin(payment_id="p1", amount=PRICE, user_id=1, invoice_number="1405-1")

    sent = json.loads(seen[0].content)
    assert sent["price_amount"] == 2.5 and sent["price_currency"] == "usd"
    assert sent["pay_currency"] == "usdttrc20" and sent["order_id"] == "p1"
    assert seen[0].headers["x-api-key"] == "api-key"
    assert instruction.metadata["gatewayReference"] == "5524759814"
    assert instruction.address == "TNDFkiSmBQorNFacb3735q8MnT29sMEn4F"
    assert "2.51" in (instruction.instructions_fa or "")


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        ("finished", VerificationOutcome.CONFIRMED),
        ("confirmed", VerificationOutcome.CONFIRMED),
        ("expired", VerificationOutcome.DECLINED),
        ("failed", VerificationOutcome.DECLINED),
        ("waiting", VerificationOutcome.INCONCLUSIVE),
        ("partially_paid", VerificationOutcome.INCONCLUSIVE),
    ],
)
def test_nowpayments_reads_its_status(provider: Any, status: str, outcome: Any) -> None:
    provider(lambda r: httpx.Response(200, json={"payment_status": status}))

    result = NowPaymentsGateway(merchant_id="k").verify(
        payment_id="p1", reference="55", expected=PRICE
    )

    assert result.outcome is outcome
    if outcome is VerificationOutcome.CONFIRMED:
        assert result.amount == PRICE


@pytest.mark.parametrize("gateway", [NowPaymentsGateway, PlisioGateway])
def test_unreachable_is_never_declined(gateway: Any, provider: Any) -> None:
    provider(_down)

    result = gateway(merchant_id="k").verify(payment_id="p1", reference="55", expected=PRICE)

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


# -- Plisio --------------------------------------------------------------------


def test_plisio_sends_the_customer_to_its_invoice(provider: Any) -> None:
    seen = provider(
        lambda r: httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"txn_id": "5f3d", "invoice_url": "https://plisio.net/invoice/5f3d"},
            },
        )
    )
    gateway = PlisioGateway(merchant_id="secret", rates=lambda: RATES)

    instruction = gateway.begin(
        payment_id="p1",
        amount=PRICE,
        user_id=1,
        invoice_number="1405-1",
        callback_url="https://shop/pay/callback/p1",
    )

    query = seen[0].url.params
    assert query["source_amount"] == "2.50" and query["source_currency"] == "USD"
    assert query["api_key"] == "secret" and query["order_number"] == "p1"
    assert instruction.redirect_url == "https://plisio.net/invoice/5f3d"
    assert instruction.metadata["gatewayReference"] == "5f3d"


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        ("completed", VerificationOutcome.CONFIRMED),
        # An overpayment: more arrived than was asked, never less.
        ("mismatch", VerificationOutcome.CONFIRMED),
        ("expired", VerificationOutcome.DECLINED),
        ("pending", VerificationOutcome.INCONCLUSIVE),
    ],
)
def test_plisio_reads_its_status(provider: Any, status: str, outcome: Any) -> None:
    provider(
        lambda r: httpx.Response(200, json={"status": "success", "data": {"status": status}})
    )

    result = PlisioGateway(merchant_id="k").verify(
        payment_id="p1", reference="5f3d", expected=PRICE
    )

    assert result.outcome is outcome


def test_a_plisio_refusal_starts_nothing(provider: Any) -> None:
    provider(
        lambda r: httpx.Response(
            200, json={"status": "error", "data": {"message": "Invalid api key"}}
        )
    )

    with pytest.raises(CryptoGatewayError, match="Invalid api key"):
        PlisioGateway(merchant_id="k", rates=lambda: RATES).begin(
            payment_id="p1", amount=PRICE, user_id=1, invoice_number="1405-1"
        )


# -- TON -----------------------------------------------------------------------

ADDRESS = "UQBvW8Z5huBkMJYdnfAEM5JqTNkuWX3diqYENkWsIL0XggGG"


def _ton() -> TonGateway:
    return TonGateway(merchant_id=f"{ADDRESS}|tc-key", rates=lambda: RATES)


def test_ton_asks_for_the_amount_with_a_comment_of_its_own() -> None:
    instruction = _ton().begin(
        payment_id="9f8e7d6c5b4a39281706", amount=PRICE, user_id=1, invoice_number="1405-1"
    )

    comment = ton_comment("9f8e7d6c5b4a39281706")
    assert instruction.address == ADDRESS
    assert instruction.metadata["gatewayReference"] == f"{comment}:1250000000"
    assert format_ton(1_250_000_000) == "1.25"
    assert comment in (instruction.instructions_fa or "")
    # A button Telegram will accept: https, never ton://.
    assert (instruction.redirect_url or "").startswith("https://")


def _chain(*messages: tuple[str, int]) -> Handler:
    result = [
        {"transaction_id": {"hash": f"h{i}"}, "in_msg": {"message": text, "value": str(value)}}
        for i, (text, value) in enumerate(messages)
    ]
    return lambda r: httpx.Response(200, json={"ok": True, "result": result})


def test_ton_confirms_a_transfer_with_the_comment_and_enough_value(provider: Any) -> None:
    seen = provider(_chain(("other", 9_000_000_000), ("GVABC", 1_250_000_000)))

    result = _ton().verify(payment_id="p1", reference="GVABC:1250000000", expected=PRICE)

    assert result.outcome is VerificationOutcome.CONFIRMED
    assert seen[0].url.params["address"] == ADDRESS
    assert seen[0].url.params["api_key"] == "tc-key"


def test_ton_does_not_settle_a_short_transfer(provider: Any) -> None:
    provider(_chain(("GVABC", 1_000_000_000)))

    result = _ton().verify(payment_id="p1", reference="GVABC:1250000000", expected=PRICE)

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_ton_does_not_settle_somebody_elses_comment(provider: Any) -> None:
    provider(_chain(("GVXYZ", 5_000_000_000)))

    result = _ton().verify(payment_id="p1", reference="GVABC:1250000000", expected=PRICE)

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_ton_unreachable_is_never_declined(provider: Any) -> None:
    provider(_down)

    result = _ton().verify(payment_id="p1", reference="GVABC:1250000000", expected=PRICE)

    assert result.outcome is VerificationOutcome.INCONCLUSIVE
