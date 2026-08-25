"""An operator should not have to know a command exists.

The bot's admin area was reachable only by typing `/admin`, which nobody who
had not been told would ever find. The home screen shows the entry to someone
who already holds an admin account.

It is discovery, not access control: every handler behind that button checks
again on each call, so a customer who somehow sends the callback still gets
"this section is for administrators".
"""

from __future__ import annotations

import pytest

from geekvpn.presentation.bot.handlers.menu import home_keyboard
from geekvpn.presentation.bot.ui import admin_text as A

pytestmark = pytest.mark.unit


def _labels(markup: object) -> list[str]:
    return [button.text for row in markup.inline_keyboard for button in row]  # type: ignore[attr-defined]


def test_a_customer_does_not_see_it() -> None:
    assert A.MENU_BUTTON not in _labels(home_keyboard())


def test_an_admin_does() -> None:
    assert A.MENU_BUTTON in _labels(home_keyboard(is_admin=True))


def test_the_customer_screen_is_otherwise_identical() -> None:
    """The entry is appended, never at the cost of something a customer uses."""
    customer = _labels(home_keyboard())
    operator = _labels(home_keyboard(is_admin=True))

    assert operator[: len(customer)] == customer
    assert len(operator) == len(customer) + 1


def test_showing_it_is_not_what_grants_access() -> None:
    """The button carries no authority; the guard behind it does.

    Stated as a test because the opposite is a tempting simplification: hiding
    a button is not hiding a callback, and anyone can send one.
    """
    import inspect

    from geekvpn.presentation.bot.handlers import admin

    for name in ("on_payments", "on_tickets", "on_admins", "on_find", "on_orders"):
        handler = getattr(admin, name)
        source = inspect.getsource(handler)
        assert "_guard(scope, user)" in source, f"{name} trusts the button"
