"""An unknown payment or invoice id must be refused, not crashed on.

The review, verification and refund services all read straight from a
repository that returns `| None`. An unknown id therefore raised
`AttributeError` from inside a money movement, which surfaces as a 500 and
tells an operator nothing. These assert the clean domain error instead.
"""

from __future__ import annotations

import pytest

from geekvpn.application.payments.loaders import require_invoice, require_payment
from geekvpn.domain.payments.errors import InvoiceNotFound, PaymentNotFound


class Empty:
    """A repository that has never heard of anything."""

    def get(self, _id: str) -> None:
        return None


def test_an_unknown_payment_id_raises_a_domain_error() -> None:
    with pytest.raises(PaymentNotFound) as caught:
        require_payment(Empty(), "pay-does-not-exist")  # type: ignore[arg-type]

    assert caught.value.details["payment_id"] == "pay-does-not-exist"


def test_an_unknown_invoice_id_raises_a_domain_error() -> None:
    with pytest.raises(InvoiceNotFound) as caught:
        require_invoice(Empty(), "inv-does-not-exist")  # type: ignore[arg-type]

    assert caught.value.details["invoice_id"] == "inv-does-not-exist"


def test_the_errors_carry_distinct_codes() -> None:
    """A caller mapping these to HTTP needs to tell them apart; both are 404
    but only one means "we lost the invoice behind a payment we still have"."""
    assert PaymentNotFound.code != InvoiceNotFound.code


def test_a_found_record_is_returned_unchanged() -> None:
    marker = object()

    class Found:
        def get(self, _id: str) -> object:
            return marker

    assert require_payment(Found(), "x") is marker  # type: ignore[arg-type]
    assert require_invoice(Found(), "x") is marker  # type: ignore[arg-type]
