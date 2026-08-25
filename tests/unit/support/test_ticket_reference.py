"""The first ticket must be openable.

`next_sequence` returned a bare count, and `format_ticket_reference` refuses a
sequence of zero. So the very first ticket of a Jalali year raised
`ValueError: sequence must be positive, got 0` - which is to say the first
ticket this platform ever received could not be filed, by the bot or the Mini
App or anyone, and the customer got "something went wrong".

The second bug was hiding behind the first: the service passed the Gregorian
year to a repository counting references that print the Jalali one, so the
count would have stayed zero forever and every reference would have been
...000001 against a unique index.

The invoice path had both bugs and both are already fixed there. This pins the
ticket path to the same behaviour, and pins the invoice path beside it so the
pair cannot drift back apart.
"""

from __future__ import annotations

import pytest

from geekvpn.domain.payments.errors import PaymentValidationError
from geekvpn.domain.payments.invoice import INVOICE_PREFIX, format_invoice_number
from geekvpn.domain.support.ticket import TICKET_PREFIX, format_ticket_reference

pytestmark = pytest.mark.unit


def test_the_first_reference_of_a_year_is_one_not_zero() -> None:
    assert format_ticket_reference(year=1405, sequence=1) == "SUP-1405-000001"


def test_zero_is_refused_rather_than_formatted() -> None:
    """The guard is right; what was wrong was the number handed to it."""
    with pytest.raises(ValueError, match="positive"):
        format_ticket_reference(year=1405, sequence=0)


def test_the_reference_carries_the_jalali_year() -> None:
    """What the repository has to match on when it counts."""
    assert "1405" in format_ticket_reference(year=1405, sequence=7)
    assert "2026" not in format_ticket_reference(year=1405, sequence=7)


def test_the_repository_can_rebuild_the_prefix_it_has_to_count() -> None:
    """A prefix written out twice is two prefixes as soon as one is edited."""
    reference = format_ticket_reference(year=1405, sequence=42)

    assert reference.startswith(f"{TICKET_PREFIX}-1405-")


def test_invoices_number_the_same_way() -> None:
    """Same bug, same shape, one file over - and already fixed there.

    The two guards raise different types: invoices a domain error, tickets a
    bare `ValueError`. Left alone rather than unified, because neither is
    reachable any more and the difference costs nothing until one is.
    """
    assert format_invoice_number(year=1405, sequence=1).startswith(f"{INVOICE_PREFIX}-1405-")

    with pytest.raises(PaymentValidationError, match="positive"):
        format_invoice_number(year=1405, sequence=0)


def test_the_jalali_year_is_the_gregorian_one_minus_621() -> None:
    """It was plus, so the first references ever issued read SUP-2647-000003.

    The comment beside the arithmetic always said 2026 -> 1405; the arithmetic
    said 2647. Nobody noticed for as long as nobody could open a ticket at all.
    """
    from geekvpn.application.support.ticket_service import _gregorian_to_jalali_year

    assert _gregorian_to_jalali_year(2026) == 1405
    assert _gregorian_to_jalali_year(2025) == 1404


def test_a_reference_is_readable_by_someone_who_uses_this_calendar() -> None:
    from geekvpn.application.support.ticket_service import _gregorian_to_jalali_year

    year = _gregorian_to_jalali_year(2026)

    assert format_ticket_reference(year=year, sequence=3) == "SUP-1405-000003"
