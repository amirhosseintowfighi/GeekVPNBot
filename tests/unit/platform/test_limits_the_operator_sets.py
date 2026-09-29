"""Numbers that used to be constants: top-up limits and reminder marks.

Each one needed a deployment to change. They are settings now, validated when
written so a typo is refused at the form and not discovered by a customer.
"""

from __future__ import annotations

import pytest
from tests.unit.notifications.fakes import EPOCH, subscription
from tests.unit.notifications.world import World as NotifyWorld
from tests.unit.payments.test_checkout_service import World as PayWorld

from geekvpn.application.notifications.reminders import ReminderService
from geekvpn.application.payments.checkout_service import CheckoutService
from geekvpn.application.platform.settings_service import (
    REMINDER_EXPIRY_DAYS,
    REMINDER_TRAFFIC_PERCENTS,
    TOPUP_MAX_TOMAN,
    TOPUP_MIN_TOMAN,
)
from geekvpn.domain.base.errors import ValidationError
from geekvpn.domain.catalog.money import Money
from geekvpn.domain.notifications.schedule import ReminderThresholds, parse_thresholds
from geekvpn.domain.payments.errors import PaymentValidationError
from geekvpn.domain.payments.wallet import MAX_TOPUP, MIN_TOPUP

pytestmark = pytest.mark.unit


# -- parsing ---------------------------------------------------------------


def test_marks_are_read_in_any_order_and_with_persian_digits() -> None:
    assert parse_thresholds("۱, 7 ,3", low=1, high=60) == (7, 3, 1)


@pytest.mark.parametrize("raw", ["", "a,b", "0,3", "7,,x", 7])
def test_anything_else_is_not_a_list_of_marks(raw: object) -> None:
    assert parse_thresholds(raw, low=1, high=60) is None


def test_a_bad_list_is_refused_when_written() -> None:
    with pytest.raises(ValidationError):
        REMINDER_EXPIRY_DAYS.coerce("seven")
    with pytest.raises(ValidationError):
        REMINDER_TRAFFIC_PERCENTS.coerce("120")
    assert REMINDER_TRAFFIC_PERCENTS.coerce("70,90") == "70,90"


def test_top_up_limits_stay_inside_the_wallets_own_bounds() -> None:
    with pytest.raises(ValidationError):
        TOPUP_MIN_TOMAN.coerce(MIN_TOPUP - 1)
    with pytest.raises(ValidationError):
        TOPUP_MAX_TOMAN.coerce(MAX_TOPUP + 1)
    assert TOPUP_MIN_TOMAN.coerce(100_000) == 100_000


# -- the top-up limits are enforced where money starts moving ----------------


def checkout(low: int, high: int) -> CheckoutService:
    world = PayWorld()
    world.service._topup_limits = lambda: (low, high)
    return world.service


def test_a_top_up_under_the_shops_minimum_is_refused() -> None:
    with pytest.raises(PaymentValidationError):
        checkout(200_000, MAX_TOPUP).begin_topup(
            user_id=1001, amount=Money(150_000), gateway_key="card", jalali_year=1405
        )


def test_a_top_up_over_the_shops_maximum_is_refused() -> None:
    with pytest.raises(PaymentValidationError):
        checkout(MIN_TOPUP, 1_000_000).begin_topup(
            user_id=1001, amount=Money(2_000_000), gateway_key="card", jalali_year=1405
        )


def test_a_top_up_inside_the_range_goes_through() -> None:
    result = checkout(200_000, 1_000_000).begin_topup(
        user_id=1001, amount=Money(500_000), gateway_key="card", jalali_year=1405
    )
    # Card invoices carry a few Toman of noise so transfers can be told apart.
    assert 500_000 <= result.invoice.total.amount < 501_000


# -- the reminders follow the operator's marks -------------------------------


def with_marks(world: NotifyWorld, marks: ReminderThresholds) -> NotifyWorld:
    world.reminders = ReminderService(
        engine=world.engine,
        subscriptions=world.subscriptions,
        clock=world.clock,
        events=world.events,
        thresholds=lambda: marks,
    )
    return world


def test_an_expiry_mark_the_operator_added_is_warned_on() -> None:
    world = with_marks(NotifyWorld(), ReminderThresholds(expiry_days=(5, 2)))
    world.subscriptions.snapshots = [subscription(days_from=5, now=EPOCH)]

    assert world.reminders.run_expiration_reminders().queued == 1


def test_a_default_mark_the_operator_removed_is_silent() -> None:
    world = with_marks(NotifyWorld(), ReminderThresholds(expiry_days=(5, 2)))
    world.subscriptions.snapshots = [subscription(days_from=7, now=EPOCH)]

    assert world.reminders.run_expiration_reminders().queued == 0
