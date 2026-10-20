"""iSunnyMoney (Nabik): a redirect gateway whose every payment must end.

The operator's one hard requirement: no payment left hanging. Each one ends
confirmed, declined, or in front of a person - and these tests pin each road
to one of the three, including the ones where the gateway says nothing useful.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import VerificationOutcome
from geekvpn.infrastructure.payments import iranian_gateways as G
from geekvpn.infrastructure.payments.isunnymoney import (
    GIVE_UP_AFTER,
    PAYMENT_WINDOW,
    IsunnyMoneyError,
    IsunnyMoneyGateway,
)

pytestmark = pytest.mark.unit

PRICE = Money(250_000)
STARTED = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
MERCHANT = "merchant-key"
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch) -> Callable[..., tuple[IsunnyMoneyGateway, list[Any]]]:
    def build(
        handler: Handler, *, now: datetime = STARTED, order_id: int = 100001
    ) -> tuple[IsunnyMoneyGateway, list[httpx.Request]]:
        seen: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        transport = httpx.MockTransport(record)

        def patched(method: str, url: str, **kwargs: Any) -> httpx.Response:
            with httpx.Client(transport=transport) as client:
                return client.request(method, url, **kwargs)

        monkeypatch.setattr(httpx, "request", patched)
        return (
            IsunnyMoneyGateway(
                merchant_id=MERCHANT, next_order_id=lambda: order_id, now=lambda: now
            ),
            seen,
        )

    return build


def _ok(data: dict[str, Any]) -> Handler:
    return lambda r: httpx.Response(200, json=data)


CREATED = {
    "success": True,
    "data": {"authority": 105416, "payment_link": "https://core.isunnymoney.com/pay/105416"},
}


def _begin(gw: IsunnyMoneyGateway) -> Any:
    return gw.begin(
        payment_id="pay-1",
        amount=PRICE,
        user_id=777,
        invoice_number="1405-0042",
        callback_url="https://shop.example/pay/callback/pay-1",
    )


# -- starting a payment --------------------------------------------------------


def test_the_request_is_json_with_an_integer_order_id_in_toman(gateway: Any) -> None:
    gw, seen = gateway(_ok(CREATED), order_id=100001)

    _begin(gw)

    body = json.loads(seen[0].content)
    assert seen[0].url.path == "/request"
    assert seen[0].headers["content-type"] == "application/json"
    # An integer: as a string the gateway refuses it.
    assert body["order_id"] == 100001 and isinstance(body["order_id"], int)
    assert (body["amount"], body["currency"], body["merchant"]) == (250_000, "IRT", MERCHANT)
    assert body["callback"] == "https://shop.example/pay/callback/pay-1"


def test_the_customer_is_sent_to_the_payment_link(gateway: Any) -> None:
    gw, _ = gateway(_ok(CREATED))

    instruction = _begin(gw)

    assert instruction.redirect_url == "https://core.isunnymoney.com/pay/105416"


def test_the_reference_carries_what_verify_needs(gateway: Any) -> None:
    gw, _ = gateway(_ok(CREATED), order_id=100007)

    instruction = _begin(gw)

    reference = instruction.metadata["gatewayReference"]
    assert reference == f"105416:100007:{int(STARTED.timestamp())}"
    assert instruction.metadata["isunnyOrderId"] == "100007"


def test_a_refused_request_starts_nothing(gateway: Any) -> None:
    gw, _ = gateway(
        _ok({"success": False, "data": {"authority": 0}, "message": "درخواست تکراری می‌باشد."})
    )

    with pytest.raises(IsunnyMoneyError, match="تکراری"):
        _begin(gw)


def test_an_order_id_past_the_integer_limit_is_refused_before_sending(gateway: Any) -> None:
    """The gateway clamps a too-large id to 2147483647, and every payment
    after that would collide on it."""
    gw, seen = gateway(_ok(CREATED), order_id=2_147_483_648)

    with pytest.raises(IsunnyMoneyError):
        _begin(gw)
    assert seen == []


# -- verifying -------------------------------------------------------------------


def _verify(gateway: Any, reply: dict[str, Any] | Handler, *, after: timedelta) -> Any:
    handler = reply if callable(reply) else _ok(reply)
    gw, seen = gateway(handler, now=STARTED + after)
    reference = f"105416:100001:{int(STARTED.timestamp())}"
    return gw.verify(payment_id="pay-1", reference=reference, expected=PRICE), seen


def _paid(amount: int = 250_000, **extra: Any) -> dict[str, Any]:
    return {
        "success": True,
        "data": {
            "status": "paid",
            "amount": amount,
            "currency": "IRT",
            "trans_id": "723327634963",
            "gateway_status": "100",
            "card_number": "610433******0587",
            **extra,
        },
    }


PENDING = {
    "success": False,
    "data": {"success": False, "status": "pending", "amount": 250_000, "trans_id": None},
    "message": None,
}


def test_a_paid_payment_confirms(gateway: Any) -> None:
    result, seen = _verify(gateway, _paid(), after=timedelta(minutes=3))

    assert result.outcome is VerificationOutcome.CONFIRMED
    assert result.amount == PRICE
    body = json.loads(seen[0].content)
    assert body == {"authority": 105416, "merchant": MERCHANT}


def test_gateway_status_100_counts_as_paid(gateway: Any) -> None:
    reply = _paid()
    reply["data"]["status"] = "100"

    result, _ = _verify(gateway, reply, after=timedelta(minutes=3))

    assert result.outcome is VerificationOutcome.CONFIRMED


def test_less_than_the_price_goes_to_a_person(gateway: Any) -> None:
    result, _ = _verify(gateway, _paid(amount=200_000), after=timedelta(minutes=3))

    # Reported as it arrived; the verification service escalates a shortfall.
    assert result.outcome is VerificationOutcome.CONFIRMED
    assert result.amount == Money(200_000)


def test_pending_within_the_window_waits(gateway: Any) -> None:
    result, _ = _verify(gateway, PENDING, after=timedelta(minutes=10))

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_pending_past_the_window_is_declined_not_left_hanging(gateway: Any) -> None:
    result, _ = _verify(gateway, PENDING, after=PAYMENT_WINDOW + timedelta(minutes=1))

    assert result.outcome is VerificationOutcome.DECLINED
    assert result.message_fa


@pytest.mark.parametrize("status", ["failed", "canceled", "cancelled", "expired", "rejected"])
def test_a_dead_payment_is_declined_at_once(gateway: Any, status: str) -> None:
    reply = {"success": False, "data": {"status": status}, "message": "ناموفق"}

    result, _ = _verify(gateway, reply, after=timedelta(minutes=3))

    assert result.outcome is VerificationOutcome.DECLINED


def test_unreachable_waits_while_there_is_time(gateway: Any) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    result, _ = _verify(gateway, down, after=timedelta(minutes=30))

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_no_answer_for_hours_goes_to_a_person_rather_than_hanging(gateway: Any) -> None:
    """Declining would be wrong - it may have been paid - and waiting forever
    is what the operator ruled out. A person decides."""

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    result, _ = _verify(gateway, down, after=GIVE_UP_AFTER + timedelta(minutes=1))

    assert result.outcome is VerificationOutcome.MISMATCH


def test_an_answer_we_cannot_read_goes_to_a_person_in_the_end(gateway: Any) -> None:
    reply = {"success": False, "data": None, "message": "authority نامعتبر"}

    early, _ = _verify(gateway, reply, after=timedelta(minutes=3))
    late, _ = _verify(gateway, reply, after=GIVE_UP_AFTER + timedelta(minutes=1))

    assert early.outcome is VerificationOutcome.INCONCLUSIVE
    assert late.outcome is VerificationOutcome.MISMATCH


def test_a_malformed_reference_still_ends_with_a_person(gateway: Any) -> None:
    gw, seen = gateway(_ok(_paid()))

    result = gw.verify(payment_id="pay-1", reference="garbage", expected=PRICE)

    assert result.outcome is VerificationOutcome.MISMATCH
    assert seen == []


# -- the registry -----------------------------------------------------------------


def test_the_registry_hands_it_the_order_sequence() -> None:
    gateway = G.build("isunnymoney", MERCHANT, order_ids=lambda: 100001)

    assert gateway.next_order_id() == 100001
    assert gateway.key == "isunnymoney"
