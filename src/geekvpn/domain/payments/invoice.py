"""Invoices.

An invoice records **what is owed and why**. A payment records **an attempt to
settle it**. They are separate aggregates because one invoice can outlive
several payments: a customer whose card receipt is rejected pays the same
invoice again in crypto, and inventing a second invoice would double-count
revenue and hand the customer two different numbers for one purchase.

The invariant that matters: **once an invoice is paid, its lines are frozen.**
An invoice is the customer's evidence of what they agreed to buy at what
price. A system that can retroactively edit a settled invoice cannot be used
to settle a dispute, which is the only reason invoices exist.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import InvoiceState
from geekvpn.domain.payments.errors import (
    IllegalPaymentTransition,
    PaymentValidationError,
)
from geekvpn.domain.payments.events import InvoiceIssued

INVOICE_PREFIX: Final[str] = "GV"


def format_invoice_number(*, year: int, sequence: int) -> str:
    """Human-quotable invoice number, e.g. ``GV-1405-000173``.

    Jalali year, then a zero-padded per-year sequence. Deliberately not a
    UUID: this number gets read aloud down a phone line and typed into a
    support chat. It is also deliberately not the database id, so the id can
    change without invalidating paperwork.

    The sequence has no gaps by policy. A voided invoice keeps its number
    rather than releasing it, because a missing number in an accounting
    sequence is a question an auditor will ask.
    """
    if sequence <= 0:
        raise PaymentValidationError("Invoice sequence must be positive.")
    return f"{INVOICE_PREFIX}-{year:04d}-{sequence:06d}"


@dataclass(frozen=True, slots=True, kw_only=True)
class InvoiceLine:
    """One priced item.

    Discounts are their own lines with negative ``amount`` rather than a
    reduction of the plan's line. A customer must be able to see the list
    price they were quoted and the discount they were given as two separate
    facts; merging them hides whether a campaign ever actually applied.
    """

    title_fa: str
    amount: int
    """Signed Toman. Negative for discounts and credits."""

    quantity: int = 1
    detail_fa: str | None = None

    def __post_init__(self) -> None:
        if not self.title_fa.strip():
            raise PaymentValidationError("An invoice line needs a title.")
        if self.quantity <= 0:
            raise PaymentValidationError("An invoice line needs a positive quantity.")

    @property
    def total(self) -> int:
        return self.amount * self.quantity

    @property
    def is_discount(self) -> bool:
        return self.amount < 0


class Invoice(AggregateRoot[str]):
    """What one customer owes for one purchase."""

    __slots__ = (
        "_lines",
        "_state",
        "due_at",
        "issued_at",
        "metadata",
        "number",
        "paid_at",
        "paid_by_payment_id",
        "subject_fa",
        "user_id",
    )

    def __init__(
        self,
        invoice_id: str,
        *,
        number: str,
        user_id: int,
        subject_fa: str,
        lines: Sequence[InvoiceLine],
        issued_at: datetime,
        due_at: datetime | None = None,
        state: InvoiceState = InvoiceState.OPEN,
        paid_at: datetime | None = None,
        paid_by_payment_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        super().__init__(invoice_id)
        if not lines:
            raise PaymentValidationError("An invoice needs at least one line.")

        self.number = number
        self.user_id = user_id
        self.subject_fa = subject_fa
        self._lines: tuple[InvoiceLine, ...] = tuple(lines)
        self._state = state
        self.issued_at = issued_at
        self.due_at = due_at
        self.paid_at = paid_at
        self.paid_by_payment_id = paid_by_payment_id
        self.metadata: dict[str, str] = dict(metadata or {})

        if self.total.amount < 0:
            raise PaymentValidationError(
                "An invoice total cannot be negative.", total=self.total.amount
            )

    @classmethod
    def issue(
        cls,
        invoice_id: str,
        *,
        number: str,
        user_id: int,
        subject_fa: str,
        lines: Sequence[InvoiceLine],
        issued_at: datetime,
        due_at: datetime | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Invoice:
        invoice = cls(
            invoice_id,
            number=number,
            user_id=user_id,
            subject_fa=subject_fa,
            lines=lines,
            issued_at=issued_at,
            due_at=due_at,
            metadata=metadata,
        )
        invoice.record(
            InvoiceIssued(
                invoice_id=invoice_id,
                number=number,
                user_id=user_id,
                total=invoice.total.amount,
            )
        )
        return invoice

    # -- reading -----------------------------------------------------------

    @property
    def state(self) -> InvoiceState:
        return self._state

    @property
    def lines(self) -> tuple[InvoiceLine, ...]:
        return self._lines

    @property
    def subtotal(self) -> Money:
        """Sum of the positive lines: the list price before any discount."""
        return Money(sum(line.total for line in self._lines if not line.is_discount))

    @property
    def discount_total(self) -> Money:
        """Total given away, as a positive number."""
        return Money(-sum(line.total for line in self._lines if line.is_discount))

    @property
    def total(self) -> Money:
        """What the customer actually owes.

        Clamped at zero: a discount larger than the price yields a free order,
        never a debt owed by us.
        """
        return Money(max(0, sum(line.total for line in self._lines)))

    @property
    def is_free(self) -> bool:
        return self.total.amount == 0

    def is_overdue(self, now: datetime) -> bool:
        if self.due_at is None or self._state is not InvoiceState.OPEN:
            return False
        return now >= self.due_at

    # -- writing -----------------------------------------------------------

    def mark_paid(self, *, payment_id: str, at: datetime) -> None:
        """Settle the invoice.

        Idempotent for the *same* payment: a retried callback that reports the
        same payment twice is a no-op rather than a conflict. A *different*
        payment claiming an already-paid invoice is a genuine conflict and is
        refused, because that is a double charge.
        """
        if self._state is InvoiceState.PAID:
            if self.paid_by_payment_id == payment_id:
                return
            raise IllegalPaymentTransition(current=str(self._state), target=str(InvoiceState.PAID))
        if self._state is not InvoiceState.OPEN:
            raise IllegalPaymentTransition(current=str(self._state), target=str(InvoiceState.PAID))

        self._state = InvoiceState.PAID
        self.paid_at = at
        self.paid_by_payment_id = payment_id

    def void(self) -> None:
        """Cancel an unpaid invoice. The number is retained, never reused."""
        if self._state is not InvoiceState.OPEN:
            raise IllegalPaymentTransition(current=str(self._state), target=str(InvoiceState.VOID))
        self._state = InvoiceState.VOID

    def mark_refunded(self) -> None:
        if self._state is not InvoiceState.PAID:
            raise IllegalPaymentTransition(
                current=str(self._state), target=str(InvoiceState.REFUNDED)
            )
        self._state = InvoiceState.REFUNDED


__all__ = [
    "INVOICE_PREFIX",
    "Invoice",
    "InvoiceLine",
    "format_invoice_number",
]
