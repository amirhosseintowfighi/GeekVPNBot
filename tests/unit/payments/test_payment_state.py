"""The payment state machine and refunds.

The rules that matter commercially:

* only an APPROVED payment may provision;
* a second approval must fail rather than provision twice;
* a sweeper must never be able to undo an approval;
* refunds accumulate and flip to REFUNDED exactly at the total.
"""

from __future__ import annotations

from datetime import timedelta

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import (
    PaymentMethod,
    PaymentState,
    RefundDestination,
    RefundReason,
)
from geekvpn.domain.payments.errors import (
    IllegalPaymentTransition,
    PaymentValidationError,
    RefundExceedsPayment,
    RefundNotAllowed,
)
from geekvpn.domain.payments.payment import MIN_REASON_LENGTH, Payment
from geekvpn.domain.payments.proof import PaymentProof
from tests.unit.payments.fakes import EPOCH
from tests.unit.payments.helpers import make_payment, settled_payment

REASON_FA = "\u0631\u0633\u06cc\u062f \u0646\u0627\u062e\u0648\u0627\u0646\u0627 \u0627\u0633\u062a"
NOTE_FA = "\u0642\u0637\u0639\u06cc \u0633\u0631\u0648\u06cc\u0633"


def _card_proof(digest: str = "abc123", *, at=EPOCH) -> PaymentProof:
    return PaymentProof.for_card(file_id="tg-file-1", image_digest=digest, submitted_at=at)


def test_a_new_payment_starts_as_draft():
    payment = make_payment()
    assert payment.state is PaymentState.DRAFT
    assert payment.captured == Money(0)


def test_zero_amount_payments_cannot_exist():
    try:
        make_payment(amount=0)
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("a payment for nothing was created")


def test_gateway_payment_must_name_its_provider():
    # Without the key the payment can never be verified or reconciled later.
    try:
        make_payment(method=PaymentMethod.GATEWAY, gateway_key=None)
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("an anonymous gateway payment was created")


def test_happy_path_card_payment():
    payment = make_payment()
    payment.await_proof(expires_at=EPOCH + timedelta(hours=6))
    assert payment.state is PaymentState.AWAITING_PROOF
    assert payment.state.awaits_customer() is True

    payment.attach_proof(_card_proof())
    assert payment.state is PaymentState.PENDING_REVIEW
    assert payment.state.awaits_operator() is True

    payment.approve(at=EPOCH + timedelta(hours=1), approved_by=9)
    assert payment.state is PaymentState.APPROVED
    assert payment.captured == Money(680_000)
    assert payment.reviewed_by == 9


def test_approving_twice_is_refused_so_a_double_click_is_harmless():
    payment = settled_payment()
    try:
        payment.approve(at=EPOCH, approved_by=2)
    except IllegalPaymentTransition:
        pass
    else:
        raise AssertionError("the same payment was approved twice")


def test_expire_cannot_undo_an_approval():
    # The sweeper runs on a timer and can collide with an approval. It must
    # lose that race, not win it.
    payment = settled_payment()
    try:
        payment.expire()
    except IllegalPaymentTransition:
        pass
    else:
        raise AssertionError("a sweeper expired an approved payment")
    assert payment.state is PaymentState.APPROVED


def test_rejection_demands_a_written_reason():
    payment = make_payment()
    payment.await_proof()
    payment.attach_proof(_card_proof())

    try:
        payment.reject(at=EPOCH, reason_fa="\u0628\u062f", rejected_by=1)
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("a payment was rejected with no explanation")

    assert len(REASON_FA) >= MIN_REASON_LENGTH
    payment.reject(at=EPOCH, reason_fa=REASON_FA, rejected_by=1)
    assert payment.state is PaymentState.REJECTED
    assert payment.rejection_reason_fa == REASON_FA


def test_rejected_is_terminal():
    payment = make_payment()
    payment.await_proof()
    payment.attach_proof(_card_proof())
    payment.reject(at=EPOCH, reason_fa=REASON_FA, rejected_by=1)
    assert payment.state.is_terminal() is True

    try:
        payment.approve(at=EPOCH, approved_by=1)
    except IllegalPaymentTransition:
        pass
    else:
        raise AssertionError("a rejected payment was resurrected")


def test_a_blurred_receipt_goes_back_without_rejecting_the_sale():
    payment = make_payment()
    payment.await_proof()
    payment.attach_proof(_card_proof())
    payment.request_better_proof()

    assert payment.state is PaymentState.AWAITING_PROOF
    # The old evidence is dropped, otherwise the review queue would show a
    # receipt that has already been judged unreadable.
    assert payment.proof is None


def test_expiry_is_measured_against_the_window_not_the_clock_type():
    payment = make_payment(expires_at=EPOCH + timedelta(hours=6))
    payment.await_proof(expires_at=EPOCH + timedelta(hours=6))
    assert payment.is_expired_at(EPOCH + timedelta(hours=5)) is False
    assert payment.is_expired_at(EPOCH + timedelta(hours=7)) is True


def test_waiting_minutes_counts_from_proof_submission():
    # Not from creation: the operator's SLA starts when the customer has done
    # their part, not when they first opened the payment screen.
    payment = make_payment()
    payment.await_proof()
    payment.attach_proof(_card_proof(at=EPOCH + timedelta(hours=3)))
    assert payment.waiting_minutes(EPOCH + timedelta(hours=3, minutes=45)) == 45


# -- refunds ---------------------------------------------------------------


def _refund(payment: Payment, amount: int, *, refund_id: str):
    return payment.refund(
        Money(amount),
        refund_id=refund_id,
        reason=RefundReason.SERVICE_FAILURE,
        destination=RefundDestination.WALLET,
        note_fa=NOTE_FA,
        at=EPOCH,
        actor_id=3,
    )


def test_unsettled_payments_cannot_be_refunded():
    payment = make_payment()
    payment.await_proof()
    try:
        _refund(payment, 100_000, refund_id="r1")
    except RefundNotAllowed:
        pass
    else:
        raise AssertionError("money was returned that was never taken")


def test_partial_refunds_accumulate_and_keep_the_service_alive():
    payment = settled_payment(amount=680_000)
    _refund(payment, 200_000, refund_id="r1")

    assert payment.state is PaymentState.PARTIALLY_REFUNDED
    assert payment.refunded_total == Money(200_000)
    assert payment.refundable == Money(480_000)
    # Still settled: the customer keeps the subscription they partly paid for.
    assert payment.state.is_settled() is True
    assert payment.state.is_terminal() is False


def test_refunds_flip_to_refunded_exactly_at_the_total():
    payment = settled_payment(amount=680_000)
    _refund(payment, 200_000, refund_id="r1")
    _refund(payment, 480_000, refund_id="r2")

    assert payment.state is PaymentState.REFUNDED
    assert payment.refundable == Money(0)
    assert len(payment.refunds) == 2


def test_refunding_more_than_was_captured_is_refused():
    payment = settled_payment(amount=680_000)
    try:
        _refund(payment, 680_001, refund_id="r1")
    except RefundExceedsPayment:
        pass
    else:
        raise AssertionError("more was refunded than was ever taken")


def test_a_second_operator_cannot_refund_an_already_refunded_payment():
    payment = settled_payment(amount=680_000)
    _refund(payment, 680_000, refund_id="r1")
    try:
        _refund(payment, 1_000, refund_id="r2")
    except (RefundNotAllowed, RefundExceedsPayment):
        pass
    else:
        raise AssertionError("a fully refunded payment was refunded again")


def test_refund_demands_a_written_note():
    payment = settled_payment()
    try:
        payment.refund(
            Money(1_000),
            refund_id="r1",
            reason=RefundReason.GOODWILL,
            destination=RefundDestination.WALLET,
            note_fa="x",
            at=EPOCH,
            actor_id=3,
        )
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("an unexplained refund was accepted")


def test_refunds_are_bounded_by_what_was_captured_not_invoiced():
    # An overpayment captures more than the invoice; an underpayment is never
    # approved. The refundable ceiling therefore follows `captured`.
    payment = settled_payment(amount=680_000, captured=700_000)
    assert payment.captured == Money(700_000)
    assert payment.refundable == Money(700_000)


# -- rules that only bite once a gateway or a wallet is involved -------------


def test_approval_cannot_skip_the_review_queue():
    """A card payment goes AWAITING_PROOF -> PENDING_REVIEW -> APPROVED.

    Approving straight from AWAITING_PROOF would mean approving a payment for
    which no receipt was ever attached.
    """
    payment = make_payment()
    payment.await_proof()
    try:
        payment.approve(at=EPOCH, approved_by=1)
    except IllegalPaymentTransition:
        pass
    else:
        raise AssertionError("a payment with no receipt was approved")


def test_proof_must_match_the_chosen_method():
    """A photo is not evidence of a crypto transfer."""
    payment = make_payment(method=PaymentMethod.CRYPTO)
    payment.await_proof()
    try:
        payment.attach_proof(
            PaymentProof.for_card(file_id="f", image_digest="d", submitted_at=EPOCH)
        )
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("a card receipt was accepted for a crypto payment")


def test_wallet_payments_never_wait_for_proof():
    """There is nothing to prove: the ledger already holds the evidence."""
    payment = make_payment(method=PaymentMethod.WALLET)
    try:
        payment.await_proof()
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("a wallet payment was told to upload a receipt")


def test_a_failed_gateway_attempt_is_terminal():
    payment = make_payment(method=PaymentMethod.GATEWAY, gateway_key="zarinpal")
    payment.send_to_gateway(gateway_key="zarinpal", reference="A-100")
    payment.fail(reason="declined")
    assert payment.state is PaymentState.FAILED
    assert payment.state.is_terminal()


def test_a_gateway_payment_can_be_escalated_without_faking_a_receipt():
    """Why `flag_for_review` exists.

    When a gateway reports an amount that does not match, a human must look at
    it. Routing that through `attach_proof` would emit ProofSubmitted for a
    proof that never existed, and the admin queue would show a receipt that
    cannot be opened.
    """
    payment = make_payment(method=PaymentMethod.GATEWAY, gateway_key="zarinpal")
    payment.send_to_gateway(gateway_key="zarinpal", reference="A-100")
    payment.collect_events()
    payment.flag_for_review()
    assert payment.state is PaymentState.PENDING_REVIEW
    assert payment.proof is None
    assert "ProofSubmitted" not in [type(e).__name__ for e in payment.collect_events()]


def test_the_refund_event_reports_what_is_still_refundable():
    """The admin UI shows the remaining figure straight off the event."""
    payment = settled_payment()
    payment.refund(
        Money(80_000),
        refund_id="r1",
        reason=RefundReason.GOODWILL,
        destination=RefundDestination.WALLET,
        note_fa="\u062c\u0628\u0631\u0627\u0646 \u062e\u0633\u0627\u0631\u062a",
        at=EPOCH,
    )
    event = payment.collect_events()[0]
    assert type(event).__name__ == "PaymentRefunded"
    assert event.remaining == 600_000
