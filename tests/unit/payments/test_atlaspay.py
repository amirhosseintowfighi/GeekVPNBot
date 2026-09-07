"""AtlasPay: card-to-card, confirmed by polling rather than a callback.

The three things that make it different from every other gateway here are the
three things worth pinning:

* the customer pays a figure AtlasPay chose, not the one we quoted;
* there is no callback, so `verify` must be safe to call over and over and
  must never turn "cannot reach them" into "declined";
* the card can be read in our own chat, which is the whole reason for adding
  it - a customer who has to open somebody else's bot to see a card number is
  a customer halfway out of ours.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import VerificationOutcome
from geekvpn.infrastructure.payments.atlaspay import AtlasPayError, AtlasPayGateway

pytestmark = pytest.mark.unit

KEY = "test-key"
PRICE = Money(250_000)

CREATED = {
    "orderId": 66,
    "trackingCode": "5c23c12c9fa0c8b3",
    # Deliberately not 250000: their matcher needs a unique tail.
    "totalAmountToman": 250_739,
    "cardNumberMasked": "6037****3165",
    "paymentDeadlineAt": "2026-08-05T21:58:56.329Z",
    "customerStartLink": "https://t.me/atlaspaybot/pay?startapp=order_66_abc",
}

WITH_CARD = CREATED | {
    "cardNumber": "6037991812345678",
    "cardHolderName": "Ali Rezaei",
    "bankName": "Bank Melli",
}


def _gateway(handler) -> AtlasPayGateway:
    """Patch `httpx.request` for the duration of one test.

    Through the real transport rather than by mocking the adapter's own
    methods: what is being checked here is how it reads AtlasPay's actual
    replies, and a mocked `_call` would agree with whatever it was told.
    """
    transport = httpx.MockTransport(handler)

    def patched(method, url, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.request(method, url, **kwargs)

    httpx.request = patched  # type: ignore[assignment]
    return AtlasPayGateway(merchant_id=KEY)


@pytest.fixture(autouse=True)
def _unpatch():
    original = httpx.request
    yield
    httpx.request = original


def _begin(payload: dict, *, status: int = 200):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json=payload)

    return _gateway(handler), seen


def _start(gateway: AtlasPayGateway):
    return gateway.begin(
        payment_id="pay-1",
        amount=PRICE,
        user_id=123456789,
        invoice_number="1405-1",
    )


# -- the amount ------------------------------------------------------------


def test_the_customer_is_quoted_the_figure_atlaspay_chose():
    """Their matcher recognises a transfer by its last digits. Showing our own
    price produces a transfer that never matches, and a customer whose money
    sits unconfirmed."""
    gateway, _ = _begin(CREATED)

    assert _start(gateway).amount == Money(250_739)


def test_our_price_is_what_is_asked_for():
    gateway, seen = _begin(CREATED)

    _start(gateway)

    import json

    assert json.loads(seen[0].content)["baseAmountToman"] == 250_000


def test_a_missing_total_falls_back_to_our_price_not_to_zero():
    """A zero here would be a payment settled against nothing."""
    gateway, _ = _begin(CREATED | {"totalAmountToman": None})

    assert _start(gateway).amount == PRICE


def test_the_customer_is_named_so_their_app_opens_on_this_order():
    gateway, seen = _begin(CREATED)

    _start(gateway)

    import json

    assert json.loads(seen[0].content)["customerTelegramId"] == 123456789


# -- what the customer sees ------------------------------------------------


def test_the_card_is_shown_in_our_own_chat_when_they_send_it():
    """The reason for choosing this provider. A customer who must open another
    bot to read a card number is a customer halfway out of ours."""
    gateway, _ = _begin(WITH_CARD)

    body = _start(gateway).instructions_fa or ""

    assert "6037991812345678" in body
    assert "Ali Rezaei" in body


def test_the_mini_app_link_is_still_offered():
    """It is the only way to upload a receipt when the automatic matcher does
    not fire, so it is a fallback rather than a replacement."""
    gateway, _ = _begin(WITH_CARD)

    assert _start(gateway).redirect_url == CREATED["customerStartLink"]


def test_without_the_card_the_screen_says_to_use_the_link():
    """Direct display is off until AtlasPay enables it. Drawing an empty card
    would be worse than saying where to go."""
    gateway, _ = _begin(CREATED)

    body = _start(gateway).instructions_fa or ""

    assert body
    assert "6037" not in body


def test_the_card_number_is_not_kept_in_the_metadata():
    """It is rendered and discarded. Metadata is persisted on the payment row
    and read by operators; a card number has no business living there."""
    gateway, _ = _begin(WITH_CARD)

    metadata = _start(gateway).metadata

    assert "6037991812345678" not in "".join(metadata.values())


def test_their_order_id_travels_so_the_sweeper_can_ask_about_it():
    """`verify` is handed a reference and nothing else. Without this there is
    no handle to poll and the payment can never confirm."""
    gateway, _ = _begin(CREATED)

    assert _start(gateway).metadata["gatewayReference"] == "66"


def test_the_deadline_is_theirs():
    gateway, _ = _begin(CREATED)

    expires = _start(gateway).expires_at

    assert expires == datetime(2026, 8, 5, 21, 58, 56, 329000, tzinfo=UTC)


def test_a_create_with_no_order_id_is_a_failure_not_a_screen():
    gateway, _ = _begin({"totalAmountToman": 1})

    with pytest.raises(AtlasPayError):
        _start(gateway)


# -- verification ----------------------------------------------------------


def _verify(payload: dict, *, status: int = 200, reference: str = "66"):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    gateway = _gateway(handler)
    return gateway.verify(payment_id="pay-1", reference=reference, expected=PRICE)


def test_a_paid_order_confirms():
    result = _verify({"success": True, "status": "confirmed", "paid": True})

    assert result.outcome is VerificationOutcome.CONFIRMED


def test_settled_counts_as_paid_too():
    result = _verify({"success": True, "status": "settled"})

    assert result.outcome is VerificationOutcome.CONFIRMED


def test_what_actually_arrived_is_reported():
    """They resolve an underpayment in the customer's favour, and the figure
    that lands is the one the invoice must be compared against."""
    result = _verify(
        {"success": True, "status": "confirmed", "paid": True, "actualReceivedAmountToman": 249_000}
    )

    assert result.amount == Money(249_000)


def test_an_order_still_waiting_is_inconclusive_not_declined():
    result = _verify({"success": True, "status": "awaiting_payment"})

    assert result.outcome is VerificationOutcome.INCONCLUSIVE
    assert result.retry_after is not None


def test_a_receipt_under_review_is_inconclusive():
    result = _verify({"success": True, "status": "admin_review"})

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_a_status_we_do_not_know_is_inconclusive():
    """A vocabulary they extend must never read as a refusal - that fails a
    payment that may yet succeed."""
    result = _verify({"success": True, "status": "some_new_state"})

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


@pytest.mark.parametrize("status", ["rejected", "expired", "cancelled"])
def test_a_dead_order_is_declined(status: str):
    result = _verify({"success": True, "status": status})

    assert result.outcome is VerificationOutcome.DECLINED
    assert result.message_fa


def test_an_unreachable_provider_is_not_a_refusal():
    """The single most expensive mistake available here: reading "we could not
    ask" as "they said no" fails a payment the customer really made."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    gateway = _gateway(handler)
    result = gateway.verify(payment_id="pay-1", reference="66", expected=PRICE)

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_a_missing_reference_is_inconclusive_not_declined():
    result = _verify({"success": True, "status": "confirmed"}, reference="")

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


# -- registry --------------------------------------------------------------


def test_it_is_reachable_by_its_key():
    from geekvpn.infrastructure.payments.iranian_gateways import build

    gateway = build("atlaspay", KEY)

    assert gateway.key == "atlaspay"
    assert gateway.merchant_id == KEY


def test_it_does_not_promise_a_refund_it_cannot_make():
    """Settlement is in TRX to the merchant's own wallet, so there is nothing
    to reverse through this API."""
    gateway = AtlasPayGateway(merchant_id=KEY)

    result = gateway.refund(payment_id="pay-1", reference="66", amount=PRICE)

    assert not result.succeeded


def test_the_api_accepts_the_same_providers_the_registry_builds():
    """A provider the panel can save but the registry cannot construct is a
    row that silently registers nothing: the operator sees it configured and
    the payment method never appears."""
    import typing

    from geekvpn.infrastructure.payments.iranian_gateways import BUILDERS
    from geekvpn.presentation.api.routers.admin_payments import GatewayBody

    allowed = set(typing.get_args(GatewayBody.model_fields["provider"].annotation))

    assert allowed == set(BUILDERS)
