"""What a service is called on the customer's own screen.

A service bought here is named by its product and plan. A service adopted from
a pasted link has neither - there is no order behind it - so the card rendered
as a bullet between two empty strings, which is what a customer saw after a
successful claim.

The panel username is the name such a service does have, and it is the thing
support asks for first, so it is on the card either way.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from geekvpn.application.bot.read_models import SubscriptionCard, SubscriptionState
from geekvpn.presentation.bot.ui.render import subscription_button_label, subscription_detail

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 7, tzinfo=UTC)


def _card(**overrides) -> SubscriptionCard:
    fields = {
        "subscription_id": uuid.uuid4(),
        "plan_id": uuid.uuid4(),
        "product_name_fa": "گیک توربو",
        "plan_name_fa": "یک‌ماهه",
        "state": SubscriptionState.ACTIVE,
        "expires_at": datetime(2026, 10, 1, tzinfo=UTC),
        "quota_gib": 50,
        "used_gib": 3.0,
        "remote_username": "amir",
    }
    fields.update(overrides)
    return SubscriptionCard(**fields)


def test_the_username_is_on_the_detail_screen():
    assert "amir" in subscription_detail(_card(), now=NOW)


def test_an_adopted_service_is_named_by_its_username():
    """No order, so no product and no plan. Without this the button read as a
    status emoji followed by a lone bullet."""
    label = subscription_button_label(_card(product_name_fa="", plan_name_fa=""))

    assert "amir" in label
    assert "·" not in label


def test_a_bought_service_still_shows_its_plan():
    label = subscription_button_label(_card())

    assert "گیک توربو" in label
    assert "یک‌ماهه" in label


def test_a_service_with_neither_name_nor_username_still_renders():
    """A row this broken should not blank the whole list, and a card whose
    every name is empty must not produce an empty button - Telegram refuses
    those, and the refusal takes the entire screen with it."""
    label = subscription_button_label(
        _card(product_name_fa="", plan_name_fa="", remote_username="")
    )

    assert label.strip()


def test_the_username_is_selectable_rather_than_plain_text():
    """Support asks for it, so it must be tappable to copy."""
    assert "<code>amir</code>" in subscription_detail(_card(), now=NOW)
