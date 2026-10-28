"""Products named by volume are listed smallest first.

Reported: a shop with "10GB", "20GB" and "100GB" showed 100GB first. The
storefront sorted by `(sort_order, name_fa)`, and as text "100GB" comes before
"10GB" - the third character, "0", is smaller than "G". Every product is
created with sort order 0, so the name was all that decided.
"""

from __future__ import annotations

import pytest

from geekvpn.application.catalog.storefront_service import natural_key

pytestmark = pytest.mark.unit


def test_volumes_sort_by_their_number_not_their_text() -> None:
    names = ["100GB", "10GB", "20GB", "50GB"]

    assert sorted(names, key=natural_key) == ["10GB", "20GB", "50GB", "100GB"]


def test_persian_digits_count_as_numbers_too() -> None:
    names = ["۱۰۰ گیگ", "۱۰ گیگ", "۲۰ گیگ"]

    assert sorted(names, key=natural_key) == ["۱۰ گیگ", "۲۰ گیگ", "۱۰۰ گیگ"]


def test_names_without_numbers_still_sort_alphabetically() -> None:
    assert sorted(["Pro", "Lite", "Gaming"], key=natural_key) == ["Gaming", "Lite", "Pro"]


def test_a_name_with_a_number_and_one_without_can_be_compared() -> None:
    """A mixed list must not raise comparing an int with a str."""
    assert sorted(["Unlimited", "10GB"], key=natural_key) == ["10GB", "Unlimited"]
