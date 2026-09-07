"""The payment buttons say what the operator called them.

The label was a constant on each adapter class, so renaming the button a
customer taps meant a deployment. It now comes from the shop's own data - the
account row for an online gateway, a setting for card and crypto, which have
no row of their own to hang a name on.

The rule worth pinning is the blank one: an empty label must fall back to the
adapter's name rather than through to the button. Telegram refuses a button
with no caption, and the refusal takes the whole payment screen with it - so
"the operator cleared the field" would cost every method, not one.
"""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.di.sync_scope import _rename
from geekvpn.infrastructure.payments.atlaspay import AtlasPayGateway

pytestmark = pytest.mark.unit


def _gateway() -> AtlasPayGateway:
    return AtlasPayGateway(merchant_id="k")


def test_a_chosen_name_is_used():
    gateway = _gateway()

    _rename(gateway, "پرداخت آنلاین")

    assert gateway.title_fa == "پرداخت آنلاین"


def test_no_name_keeps_the_adapters_own():
    gateway = _gateway()
    original = gateway.title_fa

    _rename(gateway, None)

    assert gateway.title_fa == original


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_a_blank_name_is_not_a_name(blank: str):
    """The one that would break the screen rather than one button."""
    gateway = _gateway()
    original = gateway.title_fa

    _rename(gateway, blank)

    assert gateway.title_fa == original


def test_surrounding_space_is_trimmed():
    gateway = _gateway()

    _rename(gateway, "  درگاه من  ")

    assert gateway.title_fa == "درگاه من"


def test_the_label_the_bot_shows_is_the_one_the_registry_holds():
    """The bot builds its keyboard from `(key, title_fa)` and knows no provider
    names, so renaming here is the whole feature."""
    from geekvpn.domain.payments.gateway import GatewayRegistry

    gateway = _gateway()
    _rename(gateway, "کارت خودکار")
    registry = GatewayRegistry()
    registry.register(gateway)

    assert [(g.key, g.title_fa) for g in registry.all()] == [("atlaspay", "کارت خودکار")]
