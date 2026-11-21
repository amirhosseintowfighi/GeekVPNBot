"""A code capped at N uses is used N times, even by customers buying at once.

The cap was checked when the price was quoted, from a coupon read without a
lock, and the use was counted later by writing back the count that read held.
Two customers with a one-use code, buying in the same second, both passed the
check and both wrote "1": two discounts, and a counter that said one.

The use is now counted on the coupon row held under lock, and the cap is
checked again there - against the count every earlier buyer has committed -
before the order it belongs to is committed. A buyer who loses is refused
before any order exists.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.domain.catalog.coupon import Coupon
from geekvpn.domain.catalog.discount import Discount
from geekvpn.domain.catalog.enums import CouponKind, PublicationState
from geekvpn.domain.catalog.errors import CouponExhausted
from geekvpn.domain.catalog.money import Money
from geekvpn.infrastructure.bot.checkout import BotCheckoutAdapter

pytestmark = pytest.mark.unit

NOW = datetime(2026, 11, 20, tzinfo=UTC)


def _coupon(*, used: int, max_redemptions: int | None = 1, max_per_user: int = 1) -> Coupon:
    return Coupon(
        coupon_id=uuid.uuid4(),
        code="GIFT",
        kind=CouponKind.PUBLIC,
        discount=Discount.fixed(10_000),
        max_redemptions=max_redemptions,
        max_per_user=max_per_user,
        redemption_count=used,
        state=PublicationState.PUBLISHED,
    )


class _LockedCoupons:
    """What the locked read sees: every use committed before ours."""

    def __init__(self, coupon: Coupon, *, by_user: int = 0) -> None:
        self.coupon = coupon
        self.by_user = by_user
        self.locked = 0
        self.recorded: list[dict[str, Any]] = []

    async def get_by_code(self, code: str) -> Coupon | None:  # the unlocked read
        raise AssertionError("the use must be counted on the locked row")

    async def get_by_code_for_update(self, code: str) -> Coupon | None:
        self.locked += 1
        return self.coupon

    async def redemption_count_for_user(self, coupon_id: uuid.UUID, user_id: uuid.UUID) -> int:
        return self.by_user

    async def update(self, coupon: Coupon) -> None:
        self.coupon = coupon

    async def record_redemption(self, **kwargs: Any) -> None:
        self.recorded.append(kwargs)


def _adapter(coupons: _LockedCoupons) -> BotCheckoutAdapter:
    adapter = object.__new__(BotCheckoutAdapter)
    adapter._coupons = coupons  # type: ignore[assignment]
    adapter._clock = SimpleNamespace(now=lambda: NOW)  # type: ignore[assignment]
    return adapter


def _quote() -> Any:
    return SimpleNamespace(coupon_code="GIFT", base_price=Money(100_000), total=Money(90_000))


async def test_the_last_use_taken_by_someone_else_refuses_this_one() -> None:
    coupons = _LockedCoupons(_coupon(used=1))

    with pytest.raises(CouponExhausted):
        await _adapter(coupons)._record_coupon_use(
            _quote(), user_id=uuid.uuid4(), order_id=uuid.uuid4().hex
        )

    assert coupons.recorded == []


async def test_a_second_use_by_the_same_customer_is_refused() -> None:
    coupons = _LockedCoupons(_coupon(used=1, max_redemptions=None), by_user=1)

    with pytest.raises(CouponExhausted):
        await _adapter(coupons)._record_coupon_use(
            _quote(), user_id=uuid.uuid4(), order_id=uuid.uuid4().hex
        )


async def test_a_use_within_the_cap_is_counted_on_the_locked_row() -> None:
    coupons = _LockedCoupons(_coupon(used=0))

    await _adapter(coupons)._record_coupon_use(
        _quote(), user_id=uuid.uuid4(), order_id=uuid.uuid4().hex
    )

    assert coupons.locked == 1
    assert coupons.coupon.redemption_count == 1
    assert len(coupons.recorded) == 1


def test_the_use_is_counted_before_the_order_is_committed() -> None:
    """Counted after, a refused use would leave an order priced with a code it
    never got - and its release would then give back a use it never took."""
    source = inspect.getsource(BotCheckoutAdapter._begin)

    assert source.index("_record_coupon_use(") < source.index("self._session.commit()")
