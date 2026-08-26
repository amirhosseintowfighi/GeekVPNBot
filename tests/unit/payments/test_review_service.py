"""Manual approval and rejection - the money-in path operated by a human."""

from __future__ import annotations

from datetime import timedelta

import pytest

from geekvpn.application.payments.adapters import CARD_WINDOW
from geekvpn.application.payments.review_service import ApprovalRequest
from geekvpn.domain.payments.enums import (
    InvoiceState,
    PaymentState,
    TransactionKind,
)
from geekvpn.domain.payments.errors import (
    AmountMismatch,
    IllegalPaymentTransition,
    PaymentValidationError,
)
from geekvpn.domain.payments.proof import PaymentProof
from tests.unit.payments.world import EPOCH, USER, World

OPERATOR = 7
REASON = "\u0645\u0628\u0644\u063a \u0648\u0627\u0631\u06cc\u0632\u06cc \u0646\u0627\u062f\u0631\u0633\u062a \u0627\u0633\u062a"


def _awaiting_review(world: World, amount: int = 680_000):
    result = world.buy(gateway_key="card", amount=amount)
    world.checkout.submit_proof(
        payment_id=result.payment.id,
        proof=PaymentProof.for_card(file_id="f1", image_digest=f"d{amount}", submitted_at=EPOCH),
    )
    return result


def test_approving_settles_the_payment_and_the_invoice_together():
    world = World()
    result = _awaiting_review(world)
    payment = world.review.approve(ApprovalRequest(payment_id=result.payment.id, actor_id=OPERATOR))
    assert payment.state is PaymentState.APPROVED
    assert world.invoices.get(result.invoice.id).state is InvoiceState.PAID


def test_approval_emits_exactly_one_provisioning_trigger():
    world = World()
    result = _awaiting_review(world)
    world.review.approve(ApprovalRequest(payment_id=result.payment.id, actor_id=OPERATOR))
    assert len(world.events.of("PaymentApproved")) == 1


def test_approval_records_who_approved_it():
    world = World()
    result = _awaiting_review(world)
    payment = world.review.approve(ApprovalRequest(payment_id=result.payment.id, actor_id=OPERATOR))
    assert payment.reviewed_by == OPERATOR
    assert "payment.approve" in world.audit.actions()


def test_a_second_approver_cannot_provision_twice():
    """Two operators clicking approve in the same second."""
    world = World()
    result = _awaiting_review(world)
    world.review.approve(ApprovalRequest(payment_id=result.payment.id, actor_id=OPERATOR))
    with pytest.raises(IllegalPaymentTransition):
        world.review.approve(ApprovalRequest(payment_id=result.payment.id, actor_id=8))
    assert len(world.events.of("PaymentApproved")) == 1


def test_an_underpayment_is_never_provisioned():
    world = World()
    result = _awaiting_review(world)
    with pytest.raises(AmountMismatch):
        world.review.approve(
            ApprovalRequest(
                payment_id=result.payment.id,
                actor_id=OPERATOR,
                actual_amount=600_000,
            )
        )
    assert result.payment.state is PaymentState.PENDING_REVIEW


def test_an_overpayment_is_credited_to_the_wallet_not_pocketed():
    """The surplus is the customer's money."""
    world = World()
    result = _awaiting_review(world)
    world.review.approve(
        ApprovalRequest(payment_id=result.payment.id, actor_id=OPERATOR, actual_amount=700_000)
    )
    assert world.balance() == 700_000 - result.payment.amount.amount
    entries = world.wallets.get_or_create(USER).history(kind=TransactionKind.OVERPAYMENT)
    assert len(entries) == 1


def test_an_exact_payment_credits_nothing():
    world = World()
    result = _awaiting_review(world)
    world.review.approve(ApprovalRequest(payment_id=result.payment.id, actor_id=OPERATOR))
    assert world.balance() == 0


def test_the_captured_amount_is_what_really_arrived():
    world = World()
    result = _awaiting_review(world)
    payment = world.review.approve(
        ApprovalRequest(payment_id=result.payment.id, actor_id=OPERATOR, actual_amount=700_000)
    )
    assert payment.captured.amount == 700_000


def test_rejecting_is_terminal_and_carries_the_reason_to_the_customer():
    world = World()
    result = _awaiting_review(world)
    payment = world.review.reject(payment_id=result.payment.id, actor_id=OPERATOR, reason_fa=REASON)
    assert payment.state is PaymentState.REJECTED
    assert payment.rejection_reason_fa == REASON
    assert world.events.of("PaymentRejected")[0].reason_fa == REASON


def test_a_rejection_without_a_reason_is_refused():
    world = World()
    result = _awaiting_review(world)
    with pytest.raises(PaymentValidationError):
        world.review.reject(
            payment_id=result.payment.id, actor_id=OPERATOR, reason_fa="\u0646\u0647"
        )


def test_an_unreadable_receipt_can_be_sent_back_without_losing_the_sale():
    world = World()
    result = _awaiting_review(world)
    payment = world.review.request_better_proof(payment_id=result.payment.id, actor_id=OPERATOR)
    assert payment.state is PaymentState.AWAITING_PROOF
    assert "payment.request_proof" in world.audit.actions()


def test_the_sweeper_expires_only_payments_waiting_on_the_customer():
    world = World()
    abandoned = world.buy(gateway_key="card", amount=100_000)
    submitted = _awaiting_review(world, amount=200_000)

    world.clock.advance(CARD_WINDOW + timedelta(minutes=1))
    closed = world.review.expire_stale()

    assert closed == 1
    assert abandoned.payment.state is PaymentState.EXPIRED
    # The customer did their part; we owe them an answer, not an expiry.
    assert submitted.payment.state is PaymentState.PENDING_REVIEW


def test_the_sweeper_leaves_live_payments_alone():
    world = World()
    result = world.buy(gateway_key="card")
    world.clock.advance(CARD_WINDOW - timedelta(minutes=5))
    assert world.review.expire_stale() == 0
    assert result.payment.state is PaymentState.AWAITING_PROOF
