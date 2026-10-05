"""An operator can switch home-screen buttons off from the bot."""

from __future__ import annotations

from typing import Any

import pytest

from geekvpn.application.platform.settings_service import (
    HIDDEN_BUTTONS,
    HIDEABLE_BUTTONS,
    parse_hidden,
)
from geekvpn.domain.base.errors import ValidationError
from geekvpn.presentation.bot.handlers.menu import HIDEABLE, home_keyboard
from geekvpn.presentation.bot.ui.callbacks import NavCB

pytestmark = pytest.mark.unit


def targets(markup: Any) -> list[str]:
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def test_a_hidden_button_is_gone_and_its_row_with_it() -> None:
    markup = home_keyboard(hidden=frozenset({"faq", "support"}))

    assert NavCB(to="faq").pack() not in targets(markup)
    assert NavCB(to="support").pack() not in targets(markup)
    assert all(row for row in markup.inline_keyboard)


def test_the_shop_and_my_services_cannot_be_hidden() -> None:
    markup = home_keyboard(hidden=frozenset(HIDEABLE) | {"shop", "dashboard"})

    assert NavCB(to="shop").pack() in targets(markup)
    assert NavCB(to="dashboard").pack() in targets(markup)


def test_the_two_lists_of_hideable_buttons_agree() -> None:
    """The settings layer cannot import the bot, so the names are written twice."""
    assert set(HIDEABLE) == HIDEABLE_BUTTONS


def test_an_unknown_button_name_is_refused_when_written() -> None:
    with pytest.raises(ValidationError):
        HIDDEN_BUTTONS.coerce("faq,shop")
    assert parse_hidden("faq, support,") == {"faq", "support"}
