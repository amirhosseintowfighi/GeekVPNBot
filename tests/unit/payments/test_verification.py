"""Automatic verification - the seam a real gateway will slot into."""

from __future__ import annotations

from datetime import timedelta

from geekvpn.application.payments.checkout_service import CheckoutRequest
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import (
    PaymentMethod,
    PaymentState,
    TransactionKind,
    VerificationOutcome,
)
from geekvpn.domain.payments.gateway import (
    CheckoutInstruction,
    GatewayCapabilities,
    RefundResult,
    VerificationResult,
)
from geekvpn.domain.payments.invoice import InvoiceLine
from tests.unit.payments.helpers import PLAN_FA
from tests.unit.payments.wiring import build_world

USER = 555


class ScriptedGateway:
    """A stand-in for a future online gateway (Zarinpal, and so on).

    Written as a plain class rather than a mock because the point of the test
    is that a new provider needs nothing but this protocol.
    """

    key = "scripted"
    title_fa = "\u062f\u0631\u06af\u0627\u0647 \u0622\u0632\u0645\u0627\u06cc\u0634\u06cc"
    method = PaymentMethod.GATEWAY

    def __init__(self, result: VerificationResult) -> None:
        self._result = result
        self.calls = 0
        self.capabilities = GatewayCapabilities(
            supports_auto_verification=True,
            supports_online_refund=True,
            supports_partial_refund=True,
            requires_redirect=True,
            requires_manual_review=False,
        )

    def begin(self, *, payment_id, amount, user_id, invoice_number, **kwargs):
        return CheckoutInstruction(
            payment_id=payment_id,
            method=self.method,
            amount=amount,
            redirect_url="https://example.invalid/pay",
        )

    def verify(self, *, payment_id, reference, expected):
        self.calls += 1
        return self._result

    def refund(self, *, payment_id, amount, reference):
        return RefundResult(succeeded=True, destination=None)


def _world_with(result: VerificationResult):
    world = build_world()
    gateway = ScriptedGateway(result)
    world.gateways.register(gateway)
    order = world.checkout.begin(
        CheckoutRequest(
            user_id=USER,
            subject_fa=PLAN_FA,
            lines=[InvoiceLine(title_fa=PLAN_FA, amount=680_000)],
            gateway_key="scripted",
            jalali_year=1405,
        )
    )
    return world, gateway, order


def test_a_redirect_gateway_waits_for_the_provider():
    _world, _, order = _world_with(VerificationResult(outcome=VerificationOutcome.INCONCLUSIVE))
    assert order.payment.state is PaymentState.PENDING_GATEWAY
    assert order.instruction.redirect_url is not None


def test_a_confirmed_payment_is_settled_without_a_human():
    world, _, order = _world_with(
        VerificationResult(outcome=VerificationOutcome.CONFIRMED, amount=Money(680_000))
    )
    world.verification.verify(order.payment.id)
    payment = world.payments.get(order.payment.id)
    assert payment.state is PaymentState.APPROVED
    assert world.invoices.get(order.invoice.id).state.value == "paid"


def test_a_repeat_callback_does_not_call_the_provider_again():
    # Gateways retry their callbacks. The second one must be free and harmless.
    world, gateway, order = _world_with(
        VerificationResult(outcome=VerificationOutcome.CONFIRMED, amount=Money(680_000))
    )
    world.verification.verify(order.payment.id)
    calls_after_first = gateway.calls
    world.verification.verify(order.payment.id)
    payment = world.payments.get(order.payment.id)

    assert gateway.calls == calls_after_first
    assert payment.state is PaymentState.APPROVED


def test_a_declined_payment_fails_rather_than_lingering():
    world, _, order = _world_with(VerificationResult(outcome=VerificationOutcome.DECLINED))
    world.verification.verify(order.payment.id)
    payment = world.payments.get(order.payment.id)
    assert payment.state is PaymentState.FAILED
    assert payment.state.is_terminal() is True


def test_an_inconclusive_answer_changes_absolutely_nothing():
    # The single most useful property here: an unreachable provider must not
    # be able to cancel a customer's order.
    world, _, order = _world_with(
        VerificationResult(
            outcome=VerificationOutcome.INCONCLUSIVE,
            retry_after=timedelta(minutes=5),
        )
    )
    world.verification.verify(order.payment.id)
    payment = world.payments.get(order.payment.id)
    assert payment.state is PaymentState.PENDING_GATEWAY
    assert "payment.verify" in world.audit.actions()


def test_a_confirmed_underpayment_goes_to_a_human_not_to_provisioning():
    world, _, order = _world_with(
        VerificationResult(outcome=VerificationOutcome.CONFIRMED, amount=Money(600_000))
    )
    world.verification.verify(order.payment.id)
    payment = world.payments.get(order.payment.id)
    assert payment.state is PaymentState.PENDING_REVIEW
    assert world.invoices.get(order.invoice.id).state.value == "open"


def test_a_confirmed_overpayment_provisions_and_credits_the_surplus():
    world, _, order = _world_with(
        VerificationResult(outcome=VerificationOutcome.CONFIRMED, amount=Money(700_000))
    )
    world.verification.verify(order.payment.id)
    payment = world.payments.get(order.payment.id)
    assert payment.state is PaymentState.APPROVED
    wallet = world.wallets.get_or_create(USER)
    assert wallet.balance == Money(20_000)
    assert wallet.entries[-1].kind is TransactionKind.OVERPAYMENT


def test_a_mismatch_is_escalated_instead_of_guessed_at():
    world, _, order = _world_with(VerificationResult(outcome=VerificationOutcome.MISMATCH))
    world.verification.verify(order.payment.id)
    payment = world.payments.get(order.payment.id)
    assert payment.state is PaymentState.PENDING_REVIEW


def test_the_sweep_reports_what_it_did():
    world, _, order = _world_with(
        VerificationResult(outcome=VerificationOutcome.CONFIRMED, amount=Money(680_000))
    )
    report = world.verification.sweep()
    assert report.checked == 1
    assert report.confirmed == 1
    assert report.declined == 0
    assert world.payments.get(order.payment.id).state is PaymentState.APPROVED


def test_the_sweep_leaves_manual_payments_alone():
    # Card and crypto never sit in PENDING_GATEWAY, so the poller never sees
    # them and can never auto-approve a photograph.
    world = build_world()
    world.checkout.begin(
        CheckoutRequest(
            user_id=USER,
            subject_fa=PLAN_FA,
            lines=[InvoiceLine(title_fa=PLAN_FA, amount=680_000)],
            gateway_key="card",
            jalali_year=1405,
        )
    )
    report = world.verification.sweep()
    assert report.checked == 0
