"""A reseller's shop shows a reseller's prices.

The failure this guards is silent by construction: everything renders, every
screen works, and the number on it is ours instead of theirs. Nobody notices
until a reseller's customer pays the wrong amount - or until the reseller
notices they are selling at cost.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.catalog.pricing import PricingContext, quote_plan
from geekvpn.domain.resellers import PriceOverride, Reseller
from tests.catalog_fakes import make_plan, make_product

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 27, 9, 0, tzinfo=UTC)


def _context(**overrides) -> PricingContext:
    data = {"now": NOW}
    data.update(overrides)
    return PricingContext(**data)


def test_a_retail_price_replaces_the_list_price():
    plan = make_plan(base_price=Money(680_000))
    product = make_product()

    quote = quote_plan(
        plan=plan,
        product=product,
        context=_context(retail_prices={plan.id: Money(900_000)}),
    )

    assert quote.base_price == Money(900_000)
    assert quote.total == Money(900_000)


def test_it_replaces_rather_than_discounts():
    """Not another line on the invoice. A different shop's price is not a
    reduction of ours, and rendering it as one would show the reseller's
    customer our price crossed out - which is nobody's business but ours."""
    plan = make_plan(base_price=Money(680_000))

    quote = quote_plan(
        plan=plan,
        product=make_product(),
        context=_context(retail_prices={plan.id: Money(900_000)}),
    )

    assert all(line.amount != Money(680_000) for line in quote.lines)


def test_a_package_the_reseller_has_not_priced_keeps_the_list_price():
    """Absent rather than copied, so a later change to our list price still
    reaches their shop instead of freezing at whatever it was on the day they
    were onboarded."""
    plan = make_plan(base_price=Money(680_000))

    quote = quote_plan(plan=plan, product=make_product(), context=_context())

    assert quote.total == Money(680_000)


def test_an_override_for_another_package_does_not_leak():
    plan = make_plan(base_price=Money(680_000))

    quote = quote_plan(
        plan=plan,
        product=make_product(),
        context=_context(retail_prices={uuid.uuid4(): Money(1)}),
    )

    assert quote.total == Money(680_000)


def test_the_platforms_own_shop_prices_nothing_differently():
    """`retail_prices` defaults to empty, so every existing caller - the Mini
    App, the admin preview, the renewal job - is unaffected."""
    plan = make_plan(base_price=Money(680_000))

    assert quote_plan(
        plan=plan, product=make_product(), context=_context()
    ).total == Money(680_000)


# -- what the storefront is handed ------------------------------------------


def _reseller(**overrides) -> Reseller:
    data = {"id": uuid.uuid4(), "admin_id": uuid.uuid4(), "name_fa": "شمال"}
    data.update(overrides)
    return Reseller(**data)


def test_only_prices_the_reseller_actually_set_are_handed_over():
    """A cost override is ours, not theirs. Handing it to the storefront would
    show a reseller's customer what the reseller pays us - which is the one
    number in this system a customer must never see."""
    plan_id = uuid.uuid4()
    reseller = _reseller(
        overrides=(PriceOverride(plan_id=plan_id, cost=Money(400_000)),)
    )

    assert reseller.retail_overrides == {}


def test_a_retail_price_is_handed_over():
    plan_id = uuid.uuid4()
    reseller = _reseller(
        overrides=(
            PriceOverride(plan_id=plan_id, cost=Money(400_000), retail=Money(900_000)),
        )
    )

    assert reseller.retail_overrides == {plan_id: Money(900_000)}
