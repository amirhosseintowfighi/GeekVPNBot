"""Days, weeks and months are the shop's: Tehran's midnight, Jalali months."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from itertools import pairwise

import pytest

from geekvpn.domain.analytics.enums import Granularity
from geekvpn.domain.analytics.timeframe import DateRange, as_date, bucket_label_fa

pytestmark = pytest.mark.unit

TEHRAN = timezone(timedelta(hours=3, minutes=30))


def test_today_starts_at_midnight_in_tehran_not_utc() -> None:
    # 22:00 UTC on the 26th is already 01:30 on the 27th in Tehran.
    today = DateRange.calendar_days(1, now=datetime(2026, 11, 26, 22, 0, tzinfo=UTC))

    assert today.start == datetime(2026, 11, 27, 0, 0, tzinfo=TEHRAN)
    assert today.end == datetime(2026, 11, 28, 0, 0, tzinfo=TEHRAN)


def test_a_month_bucket_is_a_jalali_month() -> None:
    year = DateRange.calendar_days(365, now=datetime(2026, 11, 27, 12, tzinfo=UTC))
    months = year.buckets(Granularity.MONTH)

    # 1 Farvardin 1405 and 1 Azar 1405.
    assert datetime(2026, 3, 21, tzinfo=TEHRAN) in months
    assert datetime(2026, 11, 22, tzinfo=TEHRAN) in months
    assert bucket_label_fa(datetime(2026, 11, 22, tzinfo=TEHRAN), Granularity.MONTH) == "آذر ۱۴۰۵"


def test_month_buckets_tile_without_gaps() -> None:
    months = DateRange.calendar_days(400, now=datetime(2026, 11, 27, tzinfo=UTC)).buckets(
        Granularity.MONTH
    )
    lengths = {(b - a).days for a, b in pairwise(months)}

    assert lengths <= {29, 30, 31}


def test_a_sale_is_dated_by_the_shops_calendar() -> None:
    assert str(as_date(datetime(2026, 11, 26, 21, 0, tzinfo=UTC))) == "2026-11-27"
