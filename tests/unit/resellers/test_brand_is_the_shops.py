"""A reseller's bot says a reseller's name.

Their bot greeted their customers with "welcome to the Geek VPN family" - our
brand, under a name the customer believes belongs to somebody else. It is the
first message anyone sees there, and it undoes the point of a reseller having
their own bot at all.

Making the brand a placeholder creates a second failure worth guarding: a
screen that forgets to substitute it prints a literal `{brand}` to a customer.
"""

from __future__ import annotations

import re
import uuid

import pytest

from geekvpn.domain.resellers import Reseller
from geekvpn.presentation.bot.handlers.common import brand_of
from geekvpn.presentation.bot.ui import text as T

pytestmark = pytest.mark.unit

#: Every string that names the shop.
BRANDED = ("WELCOME_NEW", "SHOP_TITLE", "REF_SHARE_TEXT")


class Scope:
    def __init__(self, reseller: Reseller | None) -> None:
        self.reseller = reseller


def _reseller(**overrides) -> Reseller:
    data = {"id": uuid.uuid4(), "admin_id": uuid.uuid4(), "name_fa": "امیر وی‌پی‌ان"}
    data.update(overrides)
    return Reseller(**data)


def test_our_own_bot_uses_our_own_name():
    assert brand_of(Scope(None)) == T.BRAND


def test_a_resellers_bot_uses_theirs():
    assert brand_of(Scope(_reseller(brand_fa="امیر نت"))) == "امیر نت"


def test_a_reseller_who_has_not_chosen_gets_their_own_name_not_ours():
    """`name_fa` is what we file them under, and it is a far better default
    than our brand: a customer seeing the reseller's own name is right, and a
    customer seeing ours is the bug this exists for."""
    assert brand_of(Scope(_reseller())) == "امیر وی‌پی‌ان"


def test_a_shop_with_nothing_set_still_gets_a_name():
    """Never a blank. Whatever else is wrong, the first message a customer
    reads must not have a hole in it."""
    assert brand_of(Scope(_reseller(name_fa=""))) == T.BRAND


def test_the_platform_name_is_still_a_name():
    """It is the fallback, so it must not itself be a placeholder - which is
    exactly what a careless find-and-replace over this file would make it."""
    assert "{" not in T.BRAND
    assert T.BRAND.strip()


@pytest.mark.parametrize("name", BRANDED)
def test_every_branded_string_takes_the_shop_as_a_value(name: str):
    assert "{brand}" in getattr(T, name)


@pytest.mark.parametrize("name", BRANDED)
def test_every_branded_string_actually_substitutes(name: str):
    """A screen that forgets prints a literal `{brand}` to a customer, which is
    worse than the wrong brand because it looks broken rather than merely
    wrong."""
    template = getattr(T, name)
    fields = dict.fromkeys(re.findall(r"{(\w+)}", template), "X")
    fields["brand"] = "امیر نت"

    rendered = template.format(**fields)

    assert "امیر نت" in rendered
    assert "{brand}" not in rendered


def test_no_other_customer_string_still_hard_codes_our_name():
    """The four were found by searching. A fifth added later would be found by
    this instead of by a reseller's customer."""
    leaked = [
        name
        for name in dir(T)
        if name.isupper()
        and name != "BRAND"
        and isinstance(getattr(T, name), str)
        and T.BRAND in getattr(T, name)
    ]

    assert not leaked, f"these name our shop in a reseller's bot: {leaked}"
