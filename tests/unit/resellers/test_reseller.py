"""The reseller aggregate: what a package costs them, and what they can spend.

Money and access, so every rule here is asserted rather than assumed.
"""

from __future__ import annotations

import uuid

import pytest

from geekvpn.domain.catalog.money import Money
from geekvpn.domain.resellers import (
    InsufficientCredit,
    NodeNotAllowed,
    PriceOverride,
    Reseller,
    ResellerStatus,
    ResellerSuspended,
)
from geekvpn.domain.resellers.reseller import MAX_DISCOUNT_PERCENT

pytestmark = pytest.mark.unit

PLAN = uuid.uuid4()
OTHER_PLAN = uuid.uuid4()


def _reseller(**overrides) -> Reseller:
    data = {
        "id": uuid.uuid4(),
        "admin_id": uuid.uuid4(),
        "name_fa": "نمایندگی شمال",
    }
    data.update(overrides)
    return Reseller(**data)


# -- pricing ----------------------------------------------------------------


def test_a_percentage_comes_off_the_list_price():
    reseller = _reseller(discount_percent=30)

    assert reseller.price_for(PLAN, Money(680_000)) == Money(476_000)


def test_no_discount_means_the_list_price():
    """Zero is a real setting, not a missing one: a reseller can be onboarded
    before anybody has agreed their margin."""
    assert _reseller().price_for(PLAN, Money(680_000)) == Money(680_000)


def test_a_remainder_rounds_in_the_resellers_favour():
    """Toman is an integer, so a percentage rarely divides. Rounding down
    means the reseller is never charged a Toman more than the percentage they
    were promised, and the platform's share absorbs the difference."""
    reseller = _reseller(discount_percent=33)

    assert reseller.price_for(PLAN, Money(100)).amount == 67


def test_an_override_beats_the_percentage():
    """A trial that must not be discounted, or a long plan at a negotiated
    rate - the edges where a percentage is the wrong shape."""
    reseller = _reseller(
        discount_percent=50,
        overrides=(PriceOverride(plan_id=PLAN, price=Money(600_000)),),
    )

    assert reseller.price_for(PLAN, Money(680_000)) == Money(600_000)


def test_an_override_above_the_list_price_is_honoured():
    """That is a negotiated rate, not an error to be corrected. Silently
    clamping it would sell at a price nobody agreed to."""
    reseller = _reseller(overrides=(PriceOverride(plan_id=PLAN, price=Money(900_000)),))

    assert reseller.price_for(PLAN, Money(680_000)) == Money(900_000)


def test_an_override_applies_only_to_its_own_package():
    reseller = _reseller(
        discount_percent=50,
        overrides=(PriceOverride(plan_id=PLAN, price=Money(1)),),
    )

    assert reseller.price_for(OTHER_PLAN, Money(680_000)) == Money(340_000)


def test_a_discount_that_makes_a_package_free_is_refused():
    """A package that costs a reseller nothing is a mistake somebody made in a
    form, and it would drain panel capacity for free until anyone noticed."""
    with pytest.raises(ValueError):
        _reseller(discount_percent=100)

    with pytest.raises(ValueError):
        _reseller(discount_percent=MAX_DISCOUNT_PERCENT + 1)


def test_a_negative_discount_is_refused():
    with pytest.raises(ValueError):
        _reseller(discount_percent=-5)


# -- credit -----------------------------------------------------------------


def test_a_sale_comes_off_the_balance():
    reseller = _reseller(balance=Money(1_000_000))
    reseller.charge(Money(476_000))

    assert reseller.balance == Money(524_000)


def test_a_balance_cannot_go_negative():
    """Debt is a policy decision with a limit and a settlement process behind
    it, and this platform has neither. Discovering you have extended a hundred
    million Toman of credit by accident is not a thing to build towards."""
    reseller = _reseller(balance=Money(100_000))

    with pytest.raises(InsufficientCredit):
        reseller.charge(Money(476_000))

    assert reseller.balance == Money(100_000)


def test_the_refusal_says_how_much_is_missing():
    """The reseller's screen has to say how much to top up by, and computing
    that twice is how the two numbers drift."""
    reseller = _reseller(balance=Money(100_000))

    with pytest.raises(InsufficientCredit) as caught:
        reseller.charge(Money(476_000))

    assert caught.value.shortfall == 376_000


def test_spending_exactly_the_balance_is_allowed():
    """Off-by-one at the boundary would refuse a legitimate sale."""
    reseller = _reseller(balance=Money(476_000))
    reseller.charge(Money(476_000))

    assert reseller.balance == Money(0)


def test_a_suspended_reseller_cannot_sell():
    reseller = _reseller(balance=Money(1_000_000), status=ResellerStatus.SUSPENDED)

    with pytest.raises(ResellerSuspended):
        reseller.charge(Money(1))


def test_credit_goes_back_on_a_refund():
    reseller = _reseller(balance=Money(100_000))
    reseller.credit(Money(50_000))

    assert reseller.balance == Money(150_000)


# -- panels -----------------------------------------------------------------


def test_no_panels_chosen_means_every_panel():
    """An operator who has not restricted anything has not yet made a
    decision. Refusing to provision at all would be a strange reading of it,
    and would break every reseller the moment the feature shipped."""
    assert _reseller().may_use("de-1")


def test_a_restricted_reseller_is_held_to_their_panels():
    reseller = _reseller(allowed_node_ids=frozenset({"de-1", "nl-2"}))

    assert reseller.may_use("de-1")
    assert not reseller.may_use("tr-9")


def test_the_refusal_names_the_panel():
    reseller = _reseller(allowed_node_ids=frozenset({"de-1"}))

    with pytest.raises(NodeNotAllowed) as caught:
        reseller.require_node("tr-9")

    assert caught.value.node_id == "tr-9"
