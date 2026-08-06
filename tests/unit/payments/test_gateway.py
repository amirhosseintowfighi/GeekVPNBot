"""The future-gateway seam.

The promise this file protects: adding a real online gateway later must not
require touching the enum, the aggregate, or any caller. These tests register
a fake provider that did not exist when the domain was written and assert that
everything above it keeps working.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest

from geekvpn.application.payments.adapters import (
    CardTransferGateway,
    CryptoTransferGateway,
    WalletGateway,
)
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import (
    PaymentMethod,
    RefundDestination,
    VerificationOutcome,
)
from geekvpn.domain.payments.errors import GatewayNotRegistered
from geekvpn.domain.payments.gateway import (
    CheckoutInstruction,
    GatewayCapabilities,
    GatewayRegistry,
    PaymentGateway,
    RefundResult,
    VerificationResult,
)


@dataclass(slots=True)
class FakeOnlineGateway:
    """A provider invented entirely in this test file.

    It never imports a base class from the domain - it only matches the
    Protocol. That is the whole point of the seam.
    """

    key: str = "zarinpal"
    title_fa: str = "\u0632\u0631\u06cc\u0646\u200c\u067e\u0627\u0644"
    method: PaymentMethod = PaymentMethod.GATEWAY
    capabilities: GatewayCapabilities = GatewayCapabilities(
        supports_auto_verification=True,
        supports_online_refund=True,
        supports_partial_refund=False,
        requires_redirect=True,
        requires_manual_review=False,
        settlement_delay=timedelta(days=1),
        min_amount=10_000,
        max_amount=50_000_000,
    )

    def begin(self, *, payment_id, amount, user_id, invoice_number, callback_url=None):
        return CheckoutInstruction(
            payment_id=payment_id,
            method=PaymentMethod.GATEWAY,
            amount=amount,
            redirect_url="https://example.invalid/pay/" + payment_id,
        )

    def verify(self, *, payment_id, reference, expected):
        return VerificationResult(
            outcome=VerificationOutcome.CONFIRMED, amount=expected, reference=reference
        )

    def refund(self, *, payment_id, reference, amount):
        return RefundResult(
            succeeded=True, destination=RefundDestination.ORIGINAL, reference="rf-1"
        )


def _registry() -> GatewayRegistry:
    registry = GatewayRegistry()
    registry.register(WalletGateway())
    registry.register(
        CardTransferGateway(
            card_number="6037-9911-1111-1111",
            card_holder_fa="\u0639\u0644\u06cc \u0631\u0636\u0627\u06cc\u06cc",
            bank_name_fa="\u0645\u0644\u06cc",
        )
    )
    registry.register(CryptoTransferGateway(address="TXyz123", network="trc20"))
    return registry


def test_the_manual_adapters_satisfy_the_gateway_protocol():
    """Card and crypto are gateways too - that is why nothing branches on them."""
    for gateway in _registry().all():
        assert isinstance(gateway, PaymentGateway)


def test_a_provider_written_later_needs_no_enum_change():
    registry = _registry()
    registry.register(FakeOnlineGateway())
    assert registry.get("zarinpal").method is PaymentMethod.GATEWAY
    assert PaymentMethod.GATEWAY.value == "gateway"


def test_an_unknown_key_is_a_named_error_not_a_key_error():
    with pytest.raises(GatewayNotRegistered):
        _registry().get("nonexistent")


def test_gateways_can_be_listed_by_method():
    registry = _registry()
    assert [g.key for g in registry.for_method(PaymentMethod.CARD)] == ["card"]


def test_a_gateway_over_its_limit_is_not_offered():
    """No dead button that fails only after the customer taps it."""
    registry = _registry()
    registry.register(FakeOnlineGateway())
    keys = [g.key for g in registry.available_for(Money(5_000))]
    assert "zarinpal" not in keys
    assert "card" in keys


def test_capabilities_answer_the_refund_question_without_naming_providers():
    registry = _registry()
    registry.register(FakeOnlineGateway())
    assert not registry.get("card").capabilities.supports_online_refund
    assert registry.get("zarinpal").capabilities.supports_online_refund


def test_manual_verification_is_inconclusive_rather_than_false():
    """A photo is not machine-verifiable, and guessing "no" would lose sales."""
    card = _registry().get("card")
    result = card.verify(payment_id="p1", reference="r", expected=Money(100_000))
    assert result.outcome is VerificationOutcome.INCONCLUSIVE
    assert result.should_retry
    assert not result.confirmed


def test_a_manual_refund_declines_instead_of_raising():
    """So the caller falls back to a wallet credit rather than failing."""
    card = _registry().get("card")
    result = card.refund(payment_id="p1", reference="r", amount=Money(100_000))
    assert not result.succeeded
    assert result.destination is RefundDestination.WALLET


def test_card_checkout_carries_the_destination_card_and_invoice_number():
    card = _registry().get("card")
    instruction = card.begin(
        payment_id="p1",
        amount=Money(680_000),
        user_id=1,
        invoice_number="GV-1405-000173",
    )
    assert instruction.metadata["card_number"] == "6037-9911-1111-1111"
    assert instruction.metadata["invoice_number"] == "GV-1405-000173"
    assert instruction.needs_customer_action


def test_crypto_checkout_carries_the_address_and_network():
    crypto = _registry().get("crypto")
    instruction = crypto.begin(
        payment_id="p1", amount=Money(680_000), user_id=1, invoice_number="GV-1"
    )
    assert instruction.address == "TXyz123"
    assert instruction.network == "trc20"


def test_a_wallet_payment_needs_no_customer_action():
    wallet = _registry().get("wallet")
    instruction = wallet.begin(
        payment_id="p1", amount=Money(100_000), user_id=1, invoice_number="GV-1"
    )
    assert not instruction.needs_customer_action
