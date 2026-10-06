"""Daily traffic from absolute panel readings."""

from __future__ import annotations

from datetime import UTC, date, datetime

from geekvpn.application.provisioning.usage_history import DayUsage, daily_usage, tehran_day

TODAY = date(2026, 9, 29)


def _r(day: int, used: int) -> DayUsage:
    return DayUsage(date(2026, 9, day), used)


def test_each_day_is_the_difference_from_the_day_before():
    days = daily_usage([_r(26, 100), _r(27, 150), _r(28, 150), _r(29, 400)], today=TODAY, days=3)
    assert [(d.day.day, d.used_mib) for d in days] == [(27, 50), (28, 0), (29, 250)]


def test_the_first_reading_on_record_is_only_a_baseline():
    days = daily_usage([_r(28, 9000), _r(29, 9100)], today=TODAY, days=3)
    assert [d.used_mib for d in days] == [0, 0, 100]


def test_a_counter_reset_counts_what_was_read_since():
    days = daily_usage([_r(27, 5000), _r(28, 5100), _r(29, 30)], today=TODAY, days=2)
    assert [d.used_mib for d in days] == [100, 30]


def test_a_day_without_a_reading_shows_zero_and_the_next_one_carries_it():
    days = daily_usage([_r(26, 100), _r(28, 300)], today=TODAY, days=3)
    assert [d.used_mib for d in days] == [0, 200, 0]


def test_the_window_always_has_the_asked_length():
    assert len(daily_usage([], today=TODAY, days=30)) == 30


def test_days_are_tehran_days():
    # 21:00 UTC is 00:30 the next day in Tehran.
    assert tehran_day(datetime(2026, 9, 28, 21, 0, tzinfo=UTC)) == date(2026, 9, 29)
    assert tehran_day(datetime(2026, 9, 28, 20, 0, tzinfo=UTC)) == date(2026, 9, 28)
