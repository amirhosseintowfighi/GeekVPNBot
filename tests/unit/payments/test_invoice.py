"""Invoices: the document, as distinct from the money.

An invoice is immutable once issued. It is voided and reissued, never edited,
because a number that was shown to a customer must keep meaning what it meant.
"""

from __future__ import annotations

from datetime import timedelta

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import InvoiceState
from geekvpn.domain.payments.errors import PaymentValidationError
from geekvpn.domain.payments.invoice import (
    INVOICE_PREFIX,
    Invoice,
    InvoiceLine,
    format_invoice_number,
)
from tests.unit.payments.fakes import EPOCH
from tests.unit.payments.helpers import PLAN_FA, line, make_invoice

DISCOUNT_FA = "\u062a\u062e\u0641\u06cc\u0641 \u06a9\u0645\u067e\u06cc\u0646"


def test_invoice_number_is_jalali_year_and_padded_sequence():
    number = format_invoice_number(year=1405, sequence=42)
    assert number == f"{INVOICE_PREFIX}-1405-000042"
    # Padding is wide enough that sorting the strings sorts the invoices.
    assert format_invoice_number(year=1405, sequence=9) < number


def test_an_invoice_needs_at_least_one_line():
    try:
        Invoice.issue(
            "inv-1",
            number="GV-1405-000001",
            user_id=1,
            subject_fa=PLAN_FA,
            lines=[],
            issued_at=EPOCH,
        )
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("an invoice for nothing was issued")


def test_discount_lines_are_negative_and_reduce_the_total():
    invoice = Invoice.issue(
        "inv-1",
        number="GV-1405-000001",
        user_id=1,
        subject_fa=PLAN_FA,
        lines=[line(680_000), InvoiceLine(title_fa=DISCOUNT_FA, amount=-102_000)],
        issued_at=EPOCH,
    )
    assert invoice.subtotal == Money(680_000)
    assert invoice.discount_total == Money(102_000)
    assert invoice.total == Money(578_000)
    assert invoice.lines[1].is_discount is True


def test_quantity_multiplies_the_line_not_the_invoice():
    invoice = Invoice.issue(
        "inv-1",
        number="GV-1405-000001",
        user_id=1,
        subject_fa=PLAN_FA,
        lines=[line(200_000, quantity=3)],
        issued_at=EPOCH,
    )
    assert invoice.lines[0].total == 600_000
    assert invoice.total == Money(600_000)


def test_a_fully_discounted_invoice_is_free_but_still_exists():
    # A 100% coupon must still produce an invoice, because provisioning
    # listens for a paid invoice and nothing else.
    invoice = Invoice.issue(
        "inv-1",
        number="GV-1405-000001",
        user_id=1,
        subject_fa=PLAN_FA,
        lines=[line(680_000), InvoiceLine(title_fa=DISCOUNT_FA, amount=-680_000)],
        issued_at=EPOCH,
    )
    assert invoice.total == Money(0)
    assert invoice.is_free is True


def test_an_over_large_discount_yields_a_free_order_not_a_debt():
    # A 100% coupon, or a discount mistakenly larger than the price, must
    # produce a free order. Clamping at zero rather than raising means the
    # customer still gets an invoice, still gets a payment record, and still
    # gets provisioned - a refused invoice would simply lose the sale. We
    # never owe the customer money for buying something.
    invoice = Invoice.issue(
        "inv-1",
        number="GV-1405-000001",
        user_id=1,
        subject_fa=PLAN_FA,
        lines=[line(100_000), InvoiceLine(title_fa=DISCOUNT_FA, amount=-150_000)],
        issued_at=EPOCH,
    )
    assert invoice.total == Money(0)
    assert invoice.is_free
    assert invoice.subtotal == Money(100_000)


def test_mark_paid_is_idempotent_for_the_same_payment():
    # Callbacks arrive more than once. The second one must be a no-op, not an
    # error the customer sees.
    invoice = make_invoice()
    invoice.mark_paid(payment_id="pay-1", at=EPOCH)
    invoice.mark_paid(payment_id="pay-1", at=EPOCH + timedelta(minutes=5))
    assert invoice.state is InvoiceState.PAID
    assert invoice.paid_by_payment_id == "pay-1"


def test_a_second_payment_cannot_claim_a_paid_invoice():
    invoice = make_invoice()
    invoice.mark_paid(payment_id="pay-1", at=EPOCH)
    try:
        invoice.mark_paid(payment_id="pay-2", at=EPOCH)
    except Exception as error:
        assert type(error).__name__ != "AssertionError"
    else:
        raise AssertionError("two payments were credited to one invoice")


def test_a_paid_invoice_cannot_be_voided():
    invoice = make_invoice()
    invoice.mark_paid(payment_id="pay-1", at=EPOCH)
    try:
        invoice.void()
    except Exception as error:
        assert type(error).__name__ != "AssertionError"
    else:
        raise AssertionError("a paid invoice was voided")


def test_voiding_an_open_invoice_keeps_the_number():
    invoice = make_invoice()
    number = invoice.number
    invoice.void()
    assert invoice.state is InvoiceState.VOID
    # Never deleted, never renumbered: the number was already shown to someone.
    assert invoice.number == number


def test_refunding_marks_the_invoice_not_just_the_payment():
    invoice = make_invoice()
    invoice.mark_paid(payment_id="pay-1", at=EPOCH)
    invoice.mark_refunded()
    assert invoice.state is InvoiceState.REFUNDED


def test_overdue_only_applies_before_payment():
    invoice = make_invoice()
    invoice.due_at = EPOCH + timedelta(hours=6)
    assert invoice.is_overdue(EPOCH + timedelta(hours=7)) is True
    invoice.mark_paid(payment_id="pay-1", at=EPOCH + timedelta(hours=8))
    assert invoice.is_overdue(EPOCH + timedelta(hours=9)) is False
