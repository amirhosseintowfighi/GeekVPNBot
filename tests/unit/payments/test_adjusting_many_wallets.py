"""A gift to everyone, or taking one back, from one form."""

from __future__ import annotations

import pytest

from tests.unit.payments.wiring import build_world

pytestmark = pytest.mark.unit

REASON = "هدیهٔ نوروزی به همه"


def test_every_wallet_in_the_audience_is_credited_with_its_own_entry() -> None:
    world = build_world()

    result = world.wallet_service.adjust_many(
        user_ids=[1, 2, 3], signed_amount=20_000, actor_id=99, reason_fa=REASON
    )

    assert result.adjusted == 3
    for user in (1, 2, 3):
        assert world.wallet_service.balance(user).amount == 20_000


def test_taking_money_back_never_pushes_a_wallet_below_zero() -> None:
    world = build_world()
    world.wallet_service.adjust_many(
        user_ids=[1, 2], signed_amount=20_000, actor_id=99, reason_fa=REASON
    )
    # User 2 spent half of it in the meantime.
    world.wallet_service.adjust(user_id=2, signed_amount=-10_000, actor_id=99, reason_fa="خرید سرویس ماهانه")

    result = world.wallet_service.adjust_many(
        user_ids=[1, 2, 3], signed_amount=-20_000, actor_id=99, reason_fa="پس گرفتن هدیه"
    )

    assert (result.adjusted, result.partial, result.skipped) == (2, 1, 1)
    assert world.wallet_service.balance(1).amount == 0
    assert world.wallet_service.balance(2).amount == 0
    assert world.wallet_service.balance(3).amount == 0
