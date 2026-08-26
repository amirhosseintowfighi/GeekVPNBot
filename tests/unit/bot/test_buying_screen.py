"""The screen between reading a price and pressing pay.

It used to be the price breakdown and nothing else. A customer who tapped a
package saw a total, a discount and a cashback line, and not one word about
what they were buying - no volume, no duration, no device count, and none of
the features the operator had typed into the product. Those facts existed, and
`plan_detail` rendered them, and nothing called `plan_detail`.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.application.catalog.dto import (
    PlanView,
    PriceLineView,
    ProductView,
    QuoteView,
)
from geekvpn.presentation.bot.ui import render as R
from geekvpn.presentation.bot.ui import text as T

pytestmark = pytest.mark.unit

FEATURES = ("سرعت بدون محدودیت", "آی‌پی ثابت اختصاصی")


def _quote(*, total: int = 544_000, base: int = 680_000) -> QuoteView:
    return QuoteView(
        plan_id=uuid.uuid4(),
        product_id=uuid.uuid4(),
        base_price=base,
        total=total,
        total_discount=base - total,
        discount_percent=20,
        cashback=27_200,
        lines=(
            PriceLineView(kind="base", label="قیمت پایه", amount=base, is_deduction=False),
            PriceLineView(
                kind="campaign", label="تخفیف", amount=base - total, is_deduction=True
            ),
        ),
    )


def _plan(**overrides) -> PlanView:
    data = {
        "id": uuid.uuid4(),
        "slug": "three-months",
        "name": "سه ماهه",
        "plan_type": "volume",
        "duration_days": 90,
        "quota_gib": 120,
        "daily_quota_gib": None,
        "device_limit": 3,
        "description": "مناسب کار و تماشا.",
        "badge": "پرفروش‌ترین",
        "is_featured": True,
        "price": _quote(),
    }
    data.update(overrides)
    return PlanView(**data)


def _screen(**kwargs) -> str:
    plan = kwargs.pop("plan", None) or _plan()
    kwargs.setdefault("product_name", "گیک توربو")
    kwargs.setdefault("features", FEATURES)
    return R.plan_detail(plan, **kwargs)


def test_the_buyer_can_see_what_they_are_buying():
    """Volume, duration and device count - the three questions every customer
    asks, and the three the screen used to answer with a price."""
    body = _screen()

    assert "۱۲۰" in body
    assert T.LBL_DURATION in body
    assert T.LBL_DEVICES in body


def test_the_features_the_operator_typed_are_shown_where_they_are_sold():
    """They appeared one screen earlier, on the list of packages, and vanished
    the moment a customer picked one."""
    body = _screen()

    assert all(feature in body for feature in FEATURES)


def test_the_badge_and_the_description_are_not_dropped():
    """Both are operator-entered selling copy that nothing displayed."""
    body = _screen()

    assert "پرفروش‌ترین" in body
    assert "مناسب کار و تماشا." in body


def test_a_plan_with_nothing_written_on_it_still_renders():
    """Badge, description and features are all optional in the catalogue."""
    body = _screen(plan=_plan(badge=None, description=None), features=())

    assert "سه ماهه" in body
    assert T.LBL_TRAFFIC in body


def test_the_price_shown_is_the_re_quoted_one():
    """The review screen re-quotes with the coupon applied. Falling back to the
    plan's own price would show the customer the pre-coupon total on the very
    screen where they confirm the discounted one."""
    body = _screen(quote=_quote(total=400_000))

    assert "۴۰۰٬۰۰۰" in body or "۴۰۰,۰۰۰" in body


def test_the_reasons_to_trust_us_come_last():
    """Delivery speed, logging, devices, support - the doubts a first-time
    buyer has, answered on the screen where they decide."""
    body = _screen()

    for line in T.PLAN_TRUST.split("\n"):
        assert line in body


def test_the_receipt_heading_is_not_printed_twice():
    """`REVIEW_TITLE` carries its own emoji, and the breakdown prefixed
    another one."""
    body = _screen()

    assert body.count("\U0001f9fe") <= 1


def test_the_standalone_breakdown_still_has_its_heading():
    """Compact mode is for embedding under a title. On its own the breakdown
    is the whole screen and needs to say what it is."""
    body = R.quote_breakdown(_quote(), plan_name="سه ماهه")

    assert T.REVIEW_TITLE in body


def test_a_product_page_does_not_tell_the_customer_to_open_a_category():
    """It ended with the storefront's own copy - "open a category to see its
    packages" - on a page reached by doing exactly that, with the packages
    already listed underneath."""
    product = ProductView(
        id=uuid.uuid4(),
        slug="turbo",
        tier="gold",
        name="گیک توربو",
        tagline=None,
        description=None,
        features=FEATURES,
        icon=None,
        badge=None,
        accent_color=None,
        is_featured=True,
        plans=(_plan(),),
    )

    body = R.product_card(product)

    assert T.PRODUCT_PICK_PLAN in body
    assert T.SHOP_INTRO not in body
