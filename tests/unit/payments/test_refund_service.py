"""Refunds - the money-out path.

The rule underneath every test here: the customer must end up with their
money somewhere, even when the original method cannot take it back. Falling
back to the wallet beats returning an error to an operator who is already
talking to an unhappy customer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pytest

from geekvpn.application.payments.refund_service import RefundRequest
from geekvpn.application.payments.review_service import ApprovalRequest
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import (
    InvoiceState,
    PaymentMethod,
    PaymentState,
    RefundDestination,
    RefundReason,
    TransactionKind,
    VerificationOutcome,
)
from geekvpn.domain.payments.errors import (
    PaymentValidationError,
    RefundExceedsPayment,
    RefundNotAllowed,
)
from geekvpn.domain.payments.gateway import (
    CheckoutInstruction,
    GatewayCapabilities,
    RefundResult,
    VerificationResult,
)
from geekvpn.domain.payments.proof import PaymentProof
from tests.unit.payments.world import EPOCH, USER, World

OPERATOR = 7
NOTE = (
    "\u0642\u0637\u0639\u06cc \u0637\u0648\u0644\u0627\u0646\u06cc \u0633\u0631\u0648\u06cc\u0633"
)


@dataclass(slots=True)
class RefundableGateway:
    """A future online provider that really can push money back."""

    key: str = "zarinpal"
    title_fa: str = "\u0632\u0631\u06cc\u0646\u200c\u067e\u0627\u0644"
    method: PaymentMethod = PaymentMethod.GATEWAY
    capabilities: GatewayCapabilities = GatewayCapabilities(
        supports_auto_verification=True,
        supports_online_refund=True,
        supports_partial_refund=True,
        requires_redirect=True,
        requires_manual_review=False,
        settlement_delay=timedelta(days=1),
        min_amount=1_000,
        max_amount=50_000_000,
    )

    def begin(self, *, payment_id, amount, user_id, invoice_number, callback_url=None):
        return CheckoutInstruction(
            payment_id=payment_id,
            method=PaymentMethod.GATEWAY,
            amount=amount,
            redirect_url="https://example.invalid/" + payment_id,
        )

    def verify(self, *, payment_id, reference, expected):
        return VerificationResult(
            outcome=VerificationOutcome.CONFIRMED, amount=expected, reference=reference
        )

    def refund(self, *, payment_id, reference, amount):
        return RefundResult(
            succeeded=True, destination=RefundDestination.ORIGINAL, reference="rf-1"
        )


def _paid_by_card(world: World, amount: int = 680_000):
    """A settled card payment, the ordinary refund subject."""
    result = world.buy(gateway_key="card", amount=amount)
    world.checkout.submit_proof(
        payment_id=result.payment.id,
        proof=PaymentProof.for_card(
            file_id=f"f-{amount}", image_digest=f"d-{amount}", submitted_at=EPOCH
        ),
    )
    world.review.approve(ApprovalRequest(payment_id=result.payment.id, actor_id=OPERATOR))
    return result


def _paid(result) -> int:
    """What the card invoice actually asked for.

    Not the quoted price: a card invoice carries a few Toman of identifier so
    a reviewer can tell two transfers at the same price apart. Refund
    arithmetic is about the sum that was captured, whatever it came to.
    """
    return result.payment.amount.amount


def _request(payment_id: str, **overrides) -> RefundRequest:
    data = {
        "payment_id": payment_id,
        "actor_id": OPERATOR,
        "reason": RefundReason.SERVICE_FAILURE,
        "note_fa": NOTE,
    }
    data.update(overrides)
    return RefundRequest(**data)


def test_a_full_refund_returns_the_money_to_the_wallet():
    world = World()
    result = _paid_by_card(world)
    outcome = world.refunds.refund(_request(result.payment.id))
    assert outcome.fully_refunded
    assert outcome.wallet_credited
    assert world.balance() == _paid(result)


def test_omitting_the_amount_refunds_whatever_is_left():
    """So "refund the rest" stays safe after a partial refund."""
    world = World()
    result = _paid_by_card(world)
    world.refunds.refund(_request(result.payment.id, amount=200_000))
    outcome = world.refunds.refund(_request(result.payment.id))
    assert outcome.entry.amount == _paid(result) - 200_000
    assert world.balance() == _paid(result)


def test_a_partial_refund_keeps_the_payment_alive():
    world = World()
    result = _paid_by_card(world)
    outcome = world.refunds.refund(_request(result.payment.id, amount=200_000))
    assert not outcome.fully_refunded
    assert outcome.payment.state is PaymentState.PARTIALLY_REFUNDED
    assert outcome.payment.refundable == Money(_paid(result) - 200_000)


def test_the_invoice_is_marked_refunded_only_once_nothing_is_left():
    world = World()
    result = _paid_by_card(world)
    world.refunds.refund(_request(result.payment.id, amount=200_000))
    assert world.invoices.get(result.invoice.id).state is InvoiceState.PAID
    world.refunds.refund(_request(result.payment.id))
    assert world.invoices.get(result.invoice.id).state is InvoiceState.REFUNDED


def test_the_refund_appears_in_the_customers_transaction_history():
    world = World()
    result = _paid_by_card(world)
    world.refunds.refund(_request(result.payment.id))
    entries = world.wallets.get_or_create(USER).history(kind=TransactionKind.REFUND)
    assert len(entries) == 1
    assert entries[0].amount == _paid(result)
    assert entries[0].actor_id == OPERATOR


def test_refunding_more_than_was_captured_is_refused():
    world = World()
    result = _paid_by_card(world)
    with pytest.raises(RefundExceedsPayment):
        world.refunds.refund(_request(result.payment.id, amount=_paid(result) + 1))
    assert world.balance() == 0


def test_a_second_operator_finds_nothing_left_to_refund():
    """Two support agents working the same ticket must not pay twice."""
    world = World()
    result = _paid_by_card(world)
    world.refunds.refund(_request(result.payment.id))
    with pytest.raises(RefundNotAllowed):
        world.refunds.refund(_request(result.payment.id))
    assert world.balance() == _paid(result)


def test_an_unsettled_payment_cannot_be_refunded():
    world = World()
    result = world.buy(gateway_key="card")
    with pytest.raises(RefundNotAllowed):
        world.refunds.refund(_request(result.payment.id))


def test_a_refund_demands_a_written_note():
    """This is the sentence that gets read back during a dispute."""
    world = World()
    result = _paid_by_card(world)
    with pytest.raises(PaymentValidationError):
        world.refunds.refund(_request(result.payment.id, note_fa="\u0646\u0647"))


def test_refunding_to_the_original_card_downgrades_to_the_wallet():
    """Card-to-card cannot be reversed programmatically in Iran.

    The request is honoured in spirit rather than refused: the customer gets
    their money, in the only place we can actually put it.
    """
    world = World()
    result = _paid_by_card(world)
    outcome = world.refunds.refund(
        _request(result.payment.id, destination=RefundDestination.ORIGINAL)
    )
    assert outcome.destination is RefundDestination.WALLET
    assert world.balance() == _paid(result)


def test_a_capable_gateway_keeps_the_original_destination():
    """The same request, a provider that can honour it, no code change."""
    world = World()
    world.gateways.register(RefundableGateway())
    result = world.buy(gateway_key="zarinpal")
    world.verification.verify(result.payment.id)
    outcome = world.refunds.refund(
        _request(result.payment.id, destination=RefundDestination.ORIGINAL)
    )
    assert outcome.destination is RefundDestination.ORIGINAL
    assert not outcome.wallet_credited
    # The money went back to the card, so the wallet must not also be credited.
    assert world.balance() == 0


def test_every_refund_is_audited_with_what_remains():
    world = World()
    result = _paid_by_card(world)
    world.refunds.refund(_request(result.payment.id, amount=200_000))
    entry = next(e for e in world.audit.entries if e["action"] == "payment.refund")
    assert entry["actor_id"] == OPERATOR
    assert entry["details"]["remaining"] == _paid(result) - 200_000


def test_a_refund_publishes_the_event_provisioning_listens_for():
    world = World()
    result = _paid_by_card(world)
    world.refunds.refund(_request(result.payment.id))
    assert world.events.of("PaymentRefunded")
