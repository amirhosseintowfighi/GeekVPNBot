"""Topping up offers whatever the shop configured, not two fixed buttons.

The purchase screen was made registry-driven and this one was missed, so the
wallet top-up screen drew card and crypto as constants. Two consequences, both
seen in production: an operator who configured an online gateway could not find
its button anywhere, and a shop with no crypto address still showed "pay with
crypto" - a button that ends in an apology.

The adapter half was broken the same way: `begin_topup` returned one of exactly
two shapes, so a gateway top-up had nowhere to land even once the button
existed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from geekvpn.application.bot.read_models import GatewayScreen
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.payments.enums import PaymentMethod, PaymentState
from geekvpn.domain.payments.gateway import CheckoutInstruction
from geekvpn.infrastructure.bot.checkout import BotCheckoutAdapter
from geekvpn.presentation.bot.handlers.wallet import _method_keyboard

pytestmark = pytest.mark.unit


def test_the_top_up_screen_shows_a_button_for_every_method_the_shop_has() -> None:
    markup = _method_keyboard([("card", "کارت به کارت"), ("atlaspay", "تأیید فوری")])

    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert "کارت به کارت" in labels
    assert "تأیید فوری" in labels

    # The key travels in the callback, so an unknown provider needs no handler
    # of its own - which is exactly what a hardcoded pair could not do.
    payloads = [
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    ]
    assert any(payload.endswith("atlaspay") for payload in payloads)


def test_a_shop_with_no_crypto_address_does_not_offer_crypto() -> None:
    markup = _method_keyboard([("card", "کارت به کارت")])

    labels = [button.text for row in markup.inline_keyboard for button in row]
    assert not any("رمزارز" in label for label in labels)


class _Payment:
    id = "GV-1405-0001"
    amount = Money(200_000)
    method = PaymentMethod.GATEWAY
    state = PaymentState.PENDING_REVIEW
    created_at = datetime(2026, 9, 7, tzinfo=UTC)
    expires_at = None


class _Result:
    payment = _Payment()
    instruction = CheckoutInstruction(
        payment_id="GV-1405-0001",
        method=PaymentMethod.GATEWAY,
        amount=Money(200_137),
        redirect_url="https://t.me/atlaspay_bot?start=abc",
        instructions_fa="کارت: 6037",
    )


async def test_a_gateway_top_up_returns_the_screen_the_provider_asked_for() -> None:
    """Not a card shape. `_card_details` would have read fields the gateway
    never sent and shown the customer an empty card to transfer to."""

    class Bridge:
        async def telegram_id(self, user_id: uuid.UUID) -> int:
            return 555

        async def run(self, work):
            return _Result()

    adapter = BotCheckoutAdapter(  # type: ignore[arg-type]
        bridge=Bridge(),
        quoting=object(),
        orders=object(),
        order_repository=object(),
        provisioning=object(),
        session=object(),
        plans=object(),
        coupons=object(),
        clock=object(),
        jalali_year=1405,
    )

    screen = await adapter.begin_topup(uuid.uuid4(), amount=200_000, method="atlaspay")

    assert isinstance(screen, GatewayScreen)
    assert screen.url == "https://t.me/atlaspay_bot?start=abc"
    assert "6037" in screen.body_fa
