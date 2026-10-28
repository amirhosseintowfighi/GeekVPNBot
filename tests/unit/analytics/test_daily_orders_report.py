"""When the daily orders report goes out, and what its rates mean."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from geekvpn.application.analytics.daily_report import (
    DayOrders,
    bounds,
    day_to_report,
)

pytestmark = pytest.mark.unit


def test_the_report_is_for_the_day_that_just_ended_in_tehran() -> None:
    # 21:00 UTC is 00:30 in Tehran: the 28th has just ended there.
    now = datetime(2026, 10, 28, 21, 0, tzinfo=UTC)

    assert day_to_report(now, last_reported=None) == date(2026, 10, 28)


def test_a_day_is_reported_once() -> None:
    now = datetime(2026, 10, 29, 9, 0, tzinfo=UTC)

    assert day_to_report(now, last_reported=date(2026, 10, 28)) is None


def test_a_worker_that_was_down_at_midnight_still_sends_it() -> None:
    now = datetime(2026, 10, 29, 15, 0, tzinfo=UTC)

    assert day_to_report(now, last_reported=date(2026, 10, 27)) == date(2026, 10, 28)


def test_the_day_is_tehrans_midnight_to_midnight() -> None:
    start, end = bounds(date(2026, 10, 28))

    assert start == datetime(2026, 10, 27, 20, 30, tzinfo=UTC)
    assert end == datetime(2026, 10, 28, 20, 30, tzinfo=UTC)


def test_success_is_delivered_out_of_paid_not_out_of_placed() -> None:
    """An unpaid cart is not a failed order; counting it would make every
    abandoned checkout look like a provisioning problem."""
    day = DayOrders(date(2026, 10, 28), placed=10, delivered=6, waiting=1, failed=1, unpaid=2)

    assert day.paid == 8
    assert day.success_percent == 75
    assert day.payment_percent == 80


def test_a_quiet_day_has_no_rates_rather_than_a_division_by_zero() -> None:
    day = DayOrders(date(2026, 10, 28))

    assert day.success_percent is None
    assert day.payment_percent is None


def test_the_report_reads_in_persian_and_flags_orders_stuck_after_payment() -> None:
    from geekvpn.presentation.bot.ui.daily_report import render_daily_report

    text = render_daily_report(
        DayOrders(
            date(2026, 10, 28), placed=10, delivered=6, waiting=1, failed=1, revenue=1_500_000
        )
    )

    assert "گزارش روزانهٔ سفارش‌ها" in text
    assert "۷۵٪" in text
    assert "۱,۵۰۰,۰۰۰" in text or "۱٬۵۰۰٬۰۰۰" in text
    # One waiting and one failed: two paid orders without a service.
    assert "۲ سفارش پول داده" in text


def test_a_quiet_day_reports_no_rate_and_no_warning() -> None:
    from geekvpn.presentation.bot.ui.daily_report import NO_RATE, render_daily_report

    text = render_daily_report(DayOrders(date(2026, 10, 28)))

    assert NO_RATE in text
    assert "پول داده" not in text
