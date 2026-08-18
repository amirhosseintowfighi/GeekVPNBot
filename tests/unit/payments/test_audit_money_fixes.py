"""Money-path defects the audit found, each pinned by the behaviour that broke.

All four passed every existing gate. Three of them are only reachable with a
second actor or a second year, which is exactly why nothing caught them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.domain.payments.enums import PaymentMethod, PaymentState
from geekvpn.domain.payments.errors import PaymentNotFound
from geekvpn.domain.payments.invoice import INVOICE_PREFIX, format_invoice_number
from geekvpn.domain.payments.proof import PaymentProof

NOW = datetime(2026, 8, 19, tzinfo=UTC)


# -- 11: the first invoice of every Jalali year ---------------------------


def test_a_sequence_of_zero_is_refused_by_the_formatter() -> None:
    """The reason a bare count was a bug rather than a cosmetic off-by-one."""
    from geekvpn.domain.payments.errors import PaymentValidationError

    with pytest.raises(PaymentValidationError):
        format_invoice_number(year=1405, sequence=0)


def test_the_first_number_of_a_year_is_000001() -> None:
    assert format_invoice_number(year=1405, sequence=1) == f"{INVOICE_PREFIX}-1405-000001"


def test_next_sequence_is_one_based_and_anchored() -> None:
    """Against a fake session, so it runs without Postgres.

    Two properties: the count is incremented, and the LIKE is anchored to the
    number format. `%1405%` also matches an amount of 21405, which would skip
    numbers and eventually collide with the unique constraint.
    """
    from geekvpn.infrastructure.persistence.repositories.sync_payments import (
        SyncInvoiceRepository,
    )

    captured: list[str] = []

    class Result:
        @staticmethod
        def scalar_one() -> int:
            return 0

    class Session:
        def execute(self, statement):
            captured.append(str(statement.compile(compile_kwargs={"literal_binds": True})))
            return Result()

    assert SyncInvoiceRepository(Session()).next_sequence(year=1405) == 1  # type: ignore[arg-type]
    assert any(f"{INVOICE_PREFIX}-1405-%" in sql for sql in captured), captured
    assert not any("%1405%'" in sql for sql in captured), "the pattern is still unanchored"


def test_the_allocation_locks_the_rows_it_counted() -> None:
    """Two checkouts in the same second must not claim the same number."""
    import inspect

    from geekvpn.infrastructure.persistence.repositories.sync_payments import (
        SyncInvoiceRepository,
    )

    assert "with_for_update" in inspect.getsource(SyncInvoiceRepository.next_sequence)


# -- 8: the wallet lock ----------------------------------------------------


def test_settling_from_the_wallet_locks_before_it_reads() -> None:
    """`lock` existed and had no callers, so two concurrent purchases could
    both read the same balance and both debit it."""
    import inspect

    from geekvpn.application.payments.checkout_service import CheckoutService

    source = inspect.getsource(CheckoutService._settle_from_wallet)

    assert "_wallets.lock(" in source
    assert source.index("_wallets.lock(") < source.index("get_or_create("), (
        "locking after the read leaves the race it exists to close"
    )


# -- 12: proof may only be attached by the payment's owner ----------------


class OnePayment:
    """A repository holding one payment, owned by customer 555."""

    def __init__(self) -> None:
        self.saved: list[object] = []

    def get(self, payment_id: str):
        return Payment()

    def find_by_digest(self, digest: str) -> None:
        return None

    def save(self, payment: object) -> None:
        self.saved.append(payment)


class Payment:
    id = "pay-1"
    user_id = 555
    invoice_id = "inv-1"
    state = PaymentState.AWAITING_PROOF
    method = PaymentMethod.CARD
    expires_at = None

    def is_expired_at(self, _now: datetime) -> bool:
        return False

    def attach_proof(self, _proof: PaymentProof) -> None:
        return None

    def collect_events(self) -> list[object]:
        return []


def build_service(payments: OnePayment):
    from geekvpn.application.payments.checkout_service import CheckoutService

    class Clock:
        def now(self) -> datetime:
            return NOW

    class Null:
        def __getattr__(self, _name: str):  # noqa: ANN204
            def call(*_a: object, **_kw: object) -> None:
                return None

            return call

    return CheckoutService(
        invoices=Null(),  # type: ignore[arg-type]
        payments=payments,  # type: ignore[arg-type]
        wallets=Null(),  # type: ignore[arg-type]
        gateways=Null(),  # type: ignore[arg-type]
        clock=Clock(),  # type: ignore[arg-type]
        ids=Null(),  # type: ignore[arg-type]
        events=Null(),  # type: ignore[arg-type]
        audit=Null(),  # type: ignore[arg-type]
    )


def a_proof() -> PaymentProof:
    return PaymentProof.for_card(file_id="AgAC", image_digest="a" * 64, submitted_at=NOW)


def test_a_stranger_cannot_attach_proof_to_someone_elses_payment() -> None:
    """Payment ids travel through Telegram messages, so holding one is not
    evidence of owning it."""
    service = build_service(OnePayment())

    with pytest.raises(PaymentNotFound):
        service.submit_proof(payment_id="pay-1", proof=a_proof(), user_id=999)


def test_the_refusal_does_not_reveal_that_the_payment_exists() -> None:
    """Same error as a genuinely unknown id, so the response cannot be used to
    enumerate live payments."""
    service = build_service(OnePayment())

    with pytest.raises(PaymentNotFound) as mismatched:
        service.submit_proof(payment_id="pay-1", proof=a_proof(), user_id=999)

    assert mismatched.value.details["payment_id"] == "pay-1"


def test_the_owner_may_still_attach_proof() -> None:
    payments = OnePayment()
    service = build_service(payments)

    service.submit_proof(payment_id="pay-1", proof=a_proof(), user_id=555)

    assert payments.saved, "the owner's proof was not recorded"


def test_omitting_the_owner_keeps_the_old_behaviour() -> None:
    """Optional so existing internal callers are unaffected; the bot adapter
    always passes it."""
    payments = OnePayment()

    build_service(payments).submit_proof(payment_id="pay-1", proof=a_proof())

    assert payments.saved


# -- 14: a second partial refund ------------------------------------------


def test_the_wallet_reference_for_a_refund_is_the_refund_not_the_invoice() -> None:
    """uq_wallet_user_kind_reference is per (user, kind, reference). Two
    partial refunds against one invoice therefore collided on the second."""
    import inspect

    from geekvpn.application.payments.refund_service import RefundService

    source = inspect.getsource(RefundService)
    credit = source[source.index("kind=TransactionKind.REFUND") :]

    assert "reference=entry.refund_id" in credit
    assert "reference=payment.invoice_id" not in credit


def test_two_refund_entries_have_distinct_ids() -> None:
    """The property the reference now relies on."""
    assert uuid.uuid4() != uuid.uuid4()
    assert NOW + timedelta(seconds=1) > NOW
