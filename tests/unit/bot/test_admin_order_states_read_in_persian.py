"""The bot's admin orders list printed the raw enum value ("active")."""

from __future__ import annotations

import pytest

from geekvpn.domain.provisioning.enums import OrderState
from geekvpn.presentation.bot.ui import admin_text as A

pytestmark = pytest.mark.unit


def test_every_order_state_has_a_persian_label() -> None:
    assert set(A.ORDER_STATE_FA) == {state.value for state in OrderState}


def test_every_filter_names_a_real_state() -> None:
    states = {state.value for state in OrderState} | {""}

    assert all(value in states for _, value in A.ORDER_FILTERS)
