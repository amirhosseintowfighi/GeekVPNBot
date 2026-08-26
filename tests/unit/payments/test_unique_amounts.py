"""A card transfer must be recognisable by its amount alone.

Nobody can verify a card-to-card receipt automatically - a photograph is not
machine-readable - so a person matches the figure on the receipt to an open
invoice. Two customers buying the same plan in the same hour transfer the same
number, and that reviewer then holds two identical receipts with no way to say
which invoice each belongs to.

A few Toman of remainder on the invoice makes each amount its own name.
"""

from __future__ import annotations

import pytest

from geekvpn.application.payments.checkout_service import (
    IDENTIFIER_CEILING,
    IDENTIFIER_LINE_FA,
)
from tests.unit.payments.test_checkout_service import PLAN, World

pytestmark = pytest.mark.unit


def _remainder(result) -> int:
    return result.invoice.total.amount - 680_000


def test_two_card_invoices_at_one_price_ask_for_different_amounts():
    """The whole point. Sixteen draws from a thousand values collide about an
    eighth of the time by birthday, so this asserts on the spread, not on any
    single pair."""
    world = World()
    amounts = {world.buy(gateway_key="card").invoice.total.amount for _ in range(16)}

    assert len(amounts) > 8


def test_the_remainder_stays_under_a_thousand_toman():
    """It has to be small enough that the customer does not feel charged for
    it, and large enough to tell a day's invoices apart."""
    for _ in range(50):
        assert 1 <= _remainder(World().buy(gateway_key="card")) <= IDENTIFIER_CEILING


def test_the_remainder_is_never_zero():
    """Zero is exactly the collision this exists to prevent, and one draw in a
    thousand would otherwise land there."""
    assert all(_remainder(World().buy(gateway_key="card")) for _ in range(200))


def test_the_customer_is_charged_what_the_invoice_says():
    """The remainder is an invoice line, not a surcharge bolted on afterwards.
    If the payment and the invoice disagreed, the reviewer would be matching a
    receipt against a number the system never wrote down."""
    result = World().buy(gateway_key="card")

    assert result.payment.amount == result.invoice.total
    assert sum(line.amount for line in result.invoice.lines) == result.invoice.total.amount


def test_the_remainder_is_its_own_line_so_the_quoted_price_stays_visible():
    """A customer who was quoted 680,000 must still see 680,000 on the invoice
    beside whatever they were asked to transfer."""
    result = World().buy(gateway_key="card")
    titles = [line.title_fa for line in result.invoice.lines]

    assert PLAN in titles
    assert IDENTIFIER_LINE_FA in titles


def test_the_wallet_is_charged_the_round_number():
    """Wallet payments are matched by their id, not by a human reading an
    amount, so a remainder there would be a fee for nothing."""
    world = World()
    world.fund(1_000_000)

    assert world.buy(gateway_key="wallet").invoice.total.amount == 680_000


def test_a_free_invoice_stays_free():
    """A 100% coupon that suddenly costs 500 Toman is worse than any
    collision - and there is nothing to match, because nothing is transferred."""
    world = World()

    assert world.buy(gateway_key="card", amount=680_000, discount=680_000).invoice.total.amount == 0


def test_the_screen_the_customer_actually_reads_forbids_rounding():
    """The last three digits are the identifier. A customer who helpfully
    rounds them off hands the reviewer an unmatchable receipt, so the screen
    has to say so rather than hope.

    Asserted on the bot copy, not on the gateway's own `instructions_fa`:
    nothing displays that string, so a warning written only there would be a
    warning nobody ever sees.
    """
    from geekvpn.presentation.bot.ui.text import PAY_CARD_INSTRUCTIONS

    assert "رند نکنید" in PAY_CARD_INSTRUCTIONS
    assert "۳۰ دقیقه" in PAY_CARD_INSTRUCTIONS
    # The figure alone, in a block Telegram lets the customer tap to copy -
    # what stops them retyping it and dropping the identifier.
    assert "<code>{amount_plain}</code>" in PAY_CARD_INSTRUCTIONS


def test_the_card_the_customer_is_shown_is_the_one_the_payment_records():
    """Several active cards are handed out at random, so anything that asks
    the registry a second time gets a second draw - and the customer transfers
    to a card the payment does not name."""
    result = World().buy(gateway_key="card")

    assert result.payment.metadata["card_number"] == result.instruction.metadata["card_number"]
