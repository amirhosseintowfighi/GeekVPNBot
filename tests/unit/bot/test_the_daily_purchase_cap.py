"""A shop can cap how many new services one customer buys in a day."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from geekvpn.domain.provisioning.errors import DailyPurchaseLimitReached
from tests.unit.bot.test_checkout_adapter import build

pytestmark = pytest.mark.unit

#: 01:00 in Tehran on 6 October, still the evening of the 5th in UTC.
NOW = datetime(2026, 10, 5, 21, 30, tzinfo=UTC)


class Clock:
    def now(self) -> datetime:
        return NOW


class Orders:
    def __init__(self, bought: int) -> None:
        self.bought = bought
        self.asked_since: datetime | None = None

    async def count_new_purchases_since(self, user_id: int, since: datetime) -> int:
        self.asked_since = since
        return self.bought


def adapter(*, limit: int, bought: int) -> tuple[object, Orders]:
    orders = Orders(bought)

    async def cap() -> int:
        return limit

    return build(order_repository=orders, clock=Clock(), daily_limit=cap), orders


async def test_a_customer_at_the_cap_is_refused() -> None:
    checkout, _ = adapter(limit=2, bought=2)

    with pytest.raises(DailyPurchaseLimitReached):
        await checkout._check_daily_limit(555)  # type: ignore[attr-defined]


async def test_a_customer_under_the_cap_goes_through() -> None:
    checkout, _ = adapter(limit=2, bought=1)

    await checkout._check_daily_limit(555)  # type: ignore[attr-defined]


async def test_zero_means_no_cap_and_nothing_is_counted() -> None:
    checkout, orders = adapter(limit=0, bought=99)

    await checkout._check_daily_limit(555)  # type: ignore[attr-defined]

    assert orders.asked_since is None


async def test_the_day_starts_at_midnight_in_tehran() -> None:
    checkout, orders = adapter(limit=5, bought=0)

    await checkout._check_daily_limit(555)  # type: ignore[attr-defined]

    assert orders.asked_since is not None
    assert orders.asked_since.astimezone(UTC) == datetime(2026, 10, 5, 20, 30, tzinfo=UTC)


def test_the_refusal_explains_itself_in_persian() -> None:
    assert "سقف خرید" in DailyPurchaseLimitReached().message
