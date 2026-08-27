"""Three providers, and the unit each of them wants.

This platform stores Toman. ZarinPal and Zibal take Rial; AqayePardakht takes
Toman. A missing or a spurious factor of ten is not a bug that looks like a
bug - it is a customer charged a tenth of the price, or ten times it, with
every screen reporting success.

So the amount each adapter actually puts on the wire is pinned against one
known figure, and so is the amount each one asks the provider to verify: a
verify that names a different number than the request is a payment the provider
refuses after the customer has already paid.
"""

from __future__ import annotations

from typing import Any

import pytest

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import PaymentMethod, VerificationOutcome
from geekvpn.infrastructure.payments import iranian_gateways as G

pytestmark = pytest.mark.unit

PRICE = Money(50_000)
"""Fifty thousand Toman - half a million Rial."""


class Recorder:
    """Captures what was posted, and answers with whatever is scripted."""

    def __init__(self, reply: dict[str, Any]) -> None:
        self.reply = reply
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((url, payload))
        return self.reply


@pytest.fixture
def posted(monkeypatch: pytest.MonkeyPatch):
    def install(reply: dict[str, Any]) -> Recorder:
        recorder = Recorder(reply)
        monkeypatch.setattr(G, "_post", recorder)
        return recorder

    return install


# -- the unit ---------------------------------------------------------------


def test_zarinpal_is_billed_in_rial(posted):
    recorder = posted({"data": {"authority": "A1"}})

    G.ZarinPalGateway(merchant_id="m").begin(
        payment_id="p1", amount=PRICE, user_id=1, invoice_number="GV-1"
    )

    assert recorder.calls[0][1]["amount"] == 500_000


def test_zibal_is_billed_in_rial(posted):
    recorder = posted({"result": 100, "trackId": 77})

    G.ZibalGateway(merchant_id="m").begin(
        payment_id="p1", amount=PRICE, user_id=1, invoice_number="GV-1"
    )

    assert recorder.calls[0][1]["amount"] == 500_000


def test_aqayepardakht_is_billed_in_toman(posted):
    """The odd one out, and the reason this file exists."""
    recorder = posted({"status": "success", "transid": "T9"})

    G.AqayePardakhtGateway(merchant_id="m").begin(
        payment_id="p1", amount=PRICE, user_id=1, invoice_number="GV-1"
    )

    assert recorder.calls[0][1]["amount"] == 50_000


@pytest.mark.parametrize(
    ("gateway", "reply", "expected"),
    [
        (G.ZarinPalGateway, {"data": {"code": 100}}, 500_000),
        (G.AqayePardakhtGateway, {"code": "1"}, 50_000),
    ],
)
def test_verification_names_the_same_number_as_the_request(
    posted, gateway: Any, reply: dict[str, Any], expected: int
):
    """A verify that names a different figure is refused by the provider -
    after the customer has already paid."""
    recorder = posted(reply)

    gateway(merchant_id="m").verify(payment_id="p1", reference="A1", expected=PRICE)

    assert recorder.calls[0][1]["amount"] == expected


# -- what a customer is sent to --------------------------------------------


def test_zarinpal_sends_the_customer_to_its_own_start_page(posted):
    posted({"data": {"authority": "A1"}})

    instruction = G.ZarinPalGateway(merchant_id="m").begin(
        payment_id="p1", amount=PRICE, user_id=1, invoice_number="GV-1"
    )

    assert instruction.redirect_url.endswith("/pg/StartPay/A1")
    assert instruction.method is PaymentMethod.GATEWAY
    # The reference the callback returns with, and the one `verify` needs.
    assert instruction.metadata["authority"] == "A1"


def test_zibal_sends_the_customer_to_its_own_start_page(posted):
    posted({"result": 100, "trackId": 77})

    instruction = G.ZibalGateway(merchant_id="m").begin(
        payment_id="p1", amount=PRICE, user_id=1, invoice_number="GV-1"
    )

    assert instruction.redirect_url.endswith("/start/77")


def test_a_refused_request_raises_rather_than_returning_a_broken_link(posted):
    """A `CheckoutInstruction` with no redirect is a customer staring at a
    payment screen with nowhere to go."""
    posted({"errors": {"code": -9}})

    with pytest.raises(G.GatewayCallFailed):
        G.ZarinPalGateway(merchant_id="m").begin(
            payment_id="p1", amount=PRICE, user_id=1, invoice_number="GV-1"
        )


# -- verification ------------------------------------------------------------


@pytest.mark.parametrize(
    ("gateway", "reply"),
    [
        (G.ZarinPalGateway, {"data": {"code": 100, "ref_id": 5}}),
        (G.ZarinPalGateway, {"data": {"code": 101, "ref_id": 5}}),
        (G.ZibalGateway, {"result": 100, "refNumber": 5}),
        (G.ZibalGateway, {"result": 201, "refNumber": 5}),
        (G.AqayePardakhtGateway, {"code": "1"}),
        (G.AqayePardakhtGateway, {"code": "2"}),
    ],
)
def test_already_verified_still_counts_as_paid(posted, gateway: Any, reply: dict[str, Any]):
    """Every one of these has a distinct "already verified" answer, and every
    one of these `verify` methods is called by the callback *and* by an
    operator, sometimes at once. Treating the second answer as a failure is how
    a retried callback reverses a successful payment.
    """
    posted(reply)

    result = gateway(merchant_id="m").verify(
        payment_id="p1", reference="A1", expected=PRICE
    )

    assert result.outcome is VerificationOutcome.CONFIRMED


@pytest.mark.parametrize(
    ("gateway", "reply"),
    [
        (G.ZarinPalGateway, {"data": {"code": -51}}),
        (G.ZibalGateway, {"result": 202}),
        (G.AqayePardakhtGateway, {"code": "0"}),
    ],
)
def test_a_refusal_is_declined(posted, gateway: Any, reply: dict[str, Any]):
    posted(reply)

    result = gateway(merchant_id="m").verify(
        payment_id="p1", reference="A1", expected=PRICE
    )

    assert result.outcome is VerificationOutcome.DECLINED


@pytest.mark.parametrize(
    "gateway", [G.ZarinPalGateway, G.ZibalGateway, G.AqayePardakhtGateway]
)
def test_an_unreachable_provider_is_inconclusive_not_failed(
    monkeypatch: pytest.MonkeyPatch, gateway: Any
):
    """The most dangerous wrong answer in this file.

    "Unreachable" is not "unpaid". A DECLINED here lets the sweeper cancel a
    payment the customer completed, and they are told their money did not
    arrive when it did.
    """

    def explode(url: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise G.GatewayCallFailed("connection reset")

    monkeypatch.setattr(G, "_post", explode)

    result = gateway(merchant_id="m").verify(
        payment_id="p1", reference="A1", expected=PRICE
    )

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


# -- the registry ------------------------------------------------------------


def test_every_provider_can_be_built_by_the_key_stored_on_a_payment():
    """The key goes on the payment row forever. A provider that cannot be
    rebuilt from its own key makes that row's history unreadable."""
    for key in G.BUILDERS:
        assert G.build(key, "m").key == key


@pytest.mark.parametrize(
    "gateway", [G.ZarinPalGateway, G.ZibalGateway, G.AqayePardakhtGateway]
)
def test_none_of_them_claims_an_online_refund(gateway: Any):
    """All three refund from their own panel on a settlement cycle. Claiming
    otherwise promises a customer their money back in a way the code cannot
    deliver."""
    assert not gateway(merchant_id="m").capabilities.supports_online_refund
    assert gateway(merchant_id="m").capabilities.requires_redirect
