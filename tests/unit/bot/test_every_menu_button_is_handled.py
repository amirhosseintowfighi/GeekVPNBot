"""Every button on the persistent keyboard must have a handler.

A tap sends the button's caption verbatim. The handlers compared against the
bare label in `text.py` - "تنظیمات" - while the button says "⚙️ تنظیمات", so
eight of the nine fell straight through to "I did not understand that". The
ninth worked only because a second handler elsewhere used `contains` instead of
`==`, which is also why nobody noticed the other eight: the one button anyone
tested first was the one that worked.

Checked against the keyboard the bot actually builds, so a button added later
without a handler fails here rather than in a customer's chat.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from geekvpn.presentation.bot.ui import keyboards as K

pytestmark = pytest.mark.unit

FALLBACK = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "geekvpn"
    / "presentation"
    / "bot"
    / "handlers"
    / "fallback.py"
)


def captions() -> set[str]:
    return {
        button.text
        for row in K.main_menu().keyboard
        for button in row
        if button.text is not None
    }


def handled() -> set[str]:
    """The captions `fallback.py` compares against, resolved through `K`.

    Read from the source rather than from aiogram's filters: a magic filter
    keeps its comparison inside a closure, and reaching in would test the
    library instead of this module.
    """
    tree = ast.parse(FALLBACK.read_text(encoding="utf-8"))
    names = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr.startswith("TAP_")
        and isinstance(node.value, ast.Name)
        and node.value.id == "K"
    }
    return {getattr(K, name) for name in names}


def test_the_keyboard_has_buttons() -> None:
    assert len(captions()) >= 9


def test_every_button_is_handled() -> None:
    unhandled = captions() - handled()

    assert not unhandled, (
        "these buttons send text nothing matches, so tapping them answers "
        f'"I did not understand that": {sorted(unhandled)}'
    )


def test_no_handler_waits_for_a_button_that_is_gone() -> None:
    """The same drift in the other direction, and just as silent."""
    orphans = handled() - captions()

    assert not orphans, f"handled but on no button: {sorted(orphans)}"


def test_the_captions_carry_their_emoji() -> None:
    """Naming the exact mistake, so an edit cannot quietly undo the fix."""
    from geekvpn.presentation.bot.ui import text as T

    assert K.TAP_SETTINGS != T.MENU_SETTINGS
    assert K.TAP_SETTINGS.endswith(T.MENU_SETTINGS)
