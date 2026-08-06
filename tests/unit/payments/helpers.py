"""Small shared builders.

Every test needs an invoice and a payment, and repeating twelve keyword
arguments in each one hides the single line that the test is actually about.
"""

from __future__ import annotations

from datetime import datetime

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import PaymentMethod
from geekvpn.domain.payments.invoice import Invoice, InvoiceLine
from geekvpn.domain.payments.payment import Payment
from tests.unit.payments.fakes import EPOCH

PLAN_FA = "\u067e\u0644\u0646 \u06cc\u06a9\u200c\u0645\u0627\u0647\u0647"
DISCOUNT_FA = "\u062a\u062e\u0641\u06cc\u0641"


def line(amount: int, *, title: str = PLAN_FA, quantity: int = 1) -> InvoiceLine:
    return InvoiceLine(title_fa=title, amount=amount, quantity=quantity)


def make_invoice(
    *,
    invoice_id: str = "inv-1",
    number: str = "GV-1405-000001",
    user_id: int = 555,
    amounts: tuple[int, ...] = (680_000,),
    issued_at: datetime = EPOCH,
) -> Invoice:
    return Invoice.issue(
        invoice_id,
        number=number,
        user_id=user_id,
        subject_fa=PLAN_FA,
        lines=[line(amount) for amount in amounts],
        issued_at=issued_at,
    )


def make_payment(
    *,
    payment_id: str = "pay-1",
    invoice_id: str = "inv-1",
    user_id: int = 555,
    method: PaymentMethod = PaymentMethod.CARD,
    amount: int = 680_000,
    created_at: datetime = EPOCH,
    expires_at: datetime | None = None,
    gateway_key: str | None = None,
) -> Payment:
    return Payment.start(
        payment_id,
        invoice_id=invoice_id,
        user_id=user_id,
        method=method,
        amount=Money(amount),
        created_at=created_at,
        expires_at=expires_at,
        gateway_key=gateway_key,
    )


def settled_payment(*, amount: int = 680_000, captured: int | None = None) -> Payment:
    """A payment that has already been approved, for refund tests."""
    payment = make_payment(amount=amount)
    payment.await_proof()
    payment.flag_for_review()
    payment.approve(
        at=EPOCH,
        approved_by=1,
        captured=Money(captured) if captured is not None else None,
    )
    payment.collect_events()
    return payment


__all__ = [
    "DISCOUNT_FA",
    "PLAN_FA",
    "line",
    "make_invoice",
    "make_payment",
    "settled_payment",
]
