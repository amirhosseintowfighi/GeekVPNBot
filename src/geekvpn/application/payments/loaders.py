"""Loading a payment or invoice that must exist.

The repositories return ``| None`` because "no such row" is a real answer. The
review, verification and refund services then used the result directly, so an
unknown id produced an ``AttributeError`` deep inside a money movement instead
of a clean 404 - and every one of those call sites was a silent hazard the type
checker had been pointing at all along.

One pair of helpers rather than a guard at each of the nine call sites: the
error text and the exception type are then decided once.
"""

from __future__ import annotations

from geekvpn.application.payments.ports import InvoiceRepository, PaymentRepository
from geekvpn.domain.payments.errors import InvoiceNotFound, PaymentNotFound
from geekvpn.domain.payments.invoice import Invoice
from geekvpn.domain.payments.payment import Payment


def require_payment(payments: PaymentRepository, payment_id: str) -> Payment:
    payment = payments.get(payment_id)
    if payment is None:
        raise PaymentNotFound("The payment was not found.", payment_id=payment_id)
    return payment


def require_invoice(invoices: InvoiceRepository, invoice_id: str) -> Invoice:
    invoice = invoices.get(invoice_id)
    if invoice is None:
        raise InvoiceNotFound("The invoice was not found.", invoice_id=invoice_id)
    return invoice


__all__ = ["require_invoice", "require_payment"]
