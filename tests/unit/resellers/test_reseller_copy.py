"""A reseller rewriting the words their own bot says.

Overrides, not copies. Only the screens a shop has changed are stored, so
improving a message improves it in every shop that has not deliberately taken
it over - the opposite of seeding each new reseller with a frozen snapshot of
the text file on the day they signed up.

The dangerous edit is a deleted placeholder. A welcome without `{brand}` is the
reseller's business; a payment screen without `{amount}` is a customer who does
not know what to transfer.
"""

from __future__ import annotations

import pytest

from geekvpn.presentation.bot.ui import copy as C
from geekvpn.presentation.bot.ui import text as T

pytestmark = pytest.mark.unit


class Scope:
    def __init__(self, texts: dict[str, str] | None = None) -> None:
        self.reseller_texts = texts


def test_our_own_shop_uses_our_own_words():
    assert C.resolve(Scope(), "WELCOME_NEW") == T.WELCOME_NEW


def test_a_reseller_who_has_changed_nothing_follows_ours():
    """The point of storing overrides rather than copies: a message we improve
    reaches every shop that has not taken it over."""
    assert C.resolve(Scope({}), "SHOP_INTRO") == T.SHOP_INTRO


def test_a_rewritten_screen_says_what_they_wrote():
    assert C.resolve(Scope({"SHOP_INTRO": "سلام از امیر نت"}), "SHOP_INTRO") == "سلام از امیر نت"


def test_one_rewritten_screen_does_not_change_the_others():
    scope = Scope({"SHOP_INTRO": "x"})

    assert C.resolve(scope, "WELCOME_NEW") == T.WELCOME_NEW


def test_an_emptied_override_falls_back_rather_than_showing_nothing():
    """Clearing a message means "use the normal one", never "say nothing" - a
    blank screen is the one outcome nobody wants."""
    assert C.resolve(Scope({"SHOP_INTRO": ""}), "SHOP_INTRO") == T.SHOP_INTRO


def test_every_editable_screen_actually_exists():
    """The keys name constants in `text.py`. A rename there would otherwise
    leave a form field editing a screen that is gone, and `resolve` would hand
    the customer an empty string."""
    missing = [key for key in C.EDITABLE if not getattr(T, key, "")]

    assert not missing, missing


def test_every_editable_screen_has_a_persian_label():
    """It is rendered in a form a reseller reads."""
    for key, label in C.EDITABLE.items():
        assert label.strip(), key
        assert not label.isascii(), key


def test_the_placeholders_of_a_screen_are_known():
    """The panel refuses an edit that drops one, so it has to know which."""
    assert "brand" in C.placeholders("WELCOME_NEW")
    assert "name" in C.placeholders("WELCOME_NEW")


def test_a_screen_with_no_placeholders_reports_none():
    assert C.placeholders("SHOP_EMPTY") == ()


def test_the_list_stays_short_on_purpose():
    """Not every string in the bot.

    Routing several hundred `T.X` references through a lookup is a large change
    to every handler for a feature almost nobody uses past the first few
    screens - and most of the rest are labels and errors where a bad edit
    breaks a button rather than adding a voice.
    """
    assert len(C.EDITABLE) <= 15


def test_a_missing_screen_resolves_to_nothing_rather_than_raising():
    """`resolve` is called while rendering. An exception here is a customer
    staring at a bot that stopped answering, which is worse than a short
    message."""
    assert C.resolve(Scope(), "NOT_A_REAL_KEY") == ""
