"""A shop can keep card-to-card from people who have never bought.

Fake receipts come almost entirely from fresh accounts. Switching card off for
them leaves first-time buyers the automatic methods, where a forged image
cannot land, and gives card back once they have a purchase behind them.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.domain.payments.errors import CardNotForNewCustomers
from tests.unit.bot.test_checkout_adapter import KnownUser, build

pytestmark = pytest.mark.unit

CUSTOMER = uuid.uuid4()


class History:
    def __init__(self, bought: bool) -> None:
        self.bought = bought

    async def has_completed_order(self, telegram_id: int) -> bool:
        return self.bought


def checkout(*, allowed: bool, bought: bool) -> object:
    async def card_for_new() -> bool:
        return allowed

    return build(
        bridge=KnownUser(),
        order_repository=History(bought),
        card_for_new_customers=card_for_new,
    )


async def test_a_newcomer_is_refused_card_when_the_shop_says_so() -> None:
    with pytest.raises(CardNotForNewCustomers):
        await checkout(allowed=False, bought=False)._refuse_card_to_newcomers(CUSTOMER, "card")  # type: ignore[attr-defined]


async def test_a_returning_customer_keeps_card() -> None:
    await checkout(allowed=False, bought=True)._refuse_card_to_newcomers(CUSTOMER, "card")  # type: ignore[attr-defined]


async def test_other_methods_are_never_affected() -> None:
    await checkout(allowed=False, bought=False)._refuse_card_to_newcomers(CUSTOMER, "zarinpal")  # type: ignore[attr-defined]


async def test_by_default_everybody_may_pay_by_card() -> None:
    await checkout(allowed=True, bought=False)._refuse_card_to_newcomers(CUSTOMER, "card")  # type: ignore[attr-defined]
