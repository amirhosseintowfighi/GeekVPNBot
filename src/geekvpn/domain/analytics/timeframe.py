"""Date ranges and their buckets.

One shared range object rather than ``days: int`` parameters everywhere. The
reason is comparison: every metric on the dashboard shows a delta against the
*previous period of the same length*, and that previous period has to be
computed identically by revenue, funnels and retention or the arrows disagree.

Ranges are half-open at the end (``start <= t < end``) so consecutive periods
tile without double-counting the boundary day.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from geekvpn.domain.analytics.calendar import (
    fa_digits,
    jalali_date_fa,
    jalali_day_label,
    jalali_month_label,
)
from geekvpn.domain.analytics.enums import Granularity
from geekvpn.domain.analytics.errors import InvalidDateRange

PRESET_DAYS: tuple[int, ...] = (7, 30, 90, 365)
MAX_RANGE_DAYS = 1095


@dataclass(frozen=True, slots=True)
class DateRange:
    """A half-open UTC interval: ``start <= t < end``."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.end <= self.start:
            raise InvalidDateRange(start=self.start.isoformat(), end=self.end.isoformat())
        if self.days > MAX_RANGE_DAYS:
            raise InvalidDateRange(
                "\u0628\u0627\u0632\u0647\u0654 \u0627\u0646\u062a\u062e\u0627\u0628\u06cc \u0628\u06cc\u0634 \u0627\u0632 \u062d\u062f \u0645\u062c\u0627\u0632 \u0627\u0633\u062a.",
                days=self.days,
                maximum=MAX_RANGE_DAYS,
            )

    # ---- Construction ---------------------------------------------------

    @classmethod
    def last_days(cls, days: int, *, now: datetime) -> DateRange:
        """The last N whole days ending at ``now``."""
        if days <= 0:
            raise InvalidDateRange(days=days)
        return cls(start=now - timedelta(days=days), end=now)

    @classmethod
    def calendar_days(cls, days: int, *, now: datetime) -> DateRange:
        """The last N calendar days, snapped to midnight.

        Used for daily charts: a bucket that starts at 14:37 makes "today"
        look like a collapse every morning.
        """
        end = _midnight(now) + timedelta(days=1)
        return cls(start=end - timedelta(days=days), end=end)

    def previous(self) -> DateRange:
        """The equally long period immediately before this one."""
        span = self.end - self.start
        return DateRange(start=self.start - span, end=self.start)

    def shifted(self, delta: timedelta) -> DateRange:
        return DateRange(start=self.start + delta, end=self.end + delta)

    # ---- Queries --------------------------------------------------------

    @property
    def days(self) -> int:
        """Whole days covered, rounded up so a partial day still counts."""
        seconds = (self.end - self.start).total_seconds()
        return max(1, int((seconds + 86399) // 86400))

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def clamp(self, moment: datetime) -> datetime:
        return min(max(moment, self.start), self.end)

    def suggested_granularity(self) -> Granularity:
        """Ninety daily points is a smear; twelve monthly points is a story."""
        if self.days <= 31:
            return Granularity.DAY
        if self.days <= 120:
            return Granularity.WEEK
        return Granularity.MONTH

    def buckets(self, granularity: Granularity | None = None) -> tuple[datetime, ...]:
        """Bucket start instants covering the range, oldest first.

        Buckets are generated even where there is no data, because a gap in a
        chart must read as zero rather than as a missing week.
        """
        step = granularity or self.suggested_granularity()
        cursor = _bucket_start(self.start, step)
        out: list[datetime] = []
        while cursor < self.end:
            out.append(cursor)
            cursor = _advance(cursor, step)
        return tuple(out)

    def bucket_of(self, moment: datetime, granularity: Granularity | None = None) -> datetime:
        return _bucket_start(moment, granularity or self.suggested_granularity())

    # ---- Persian --------------------------------------------------------

    def label_fa(self) -> str:
        """``\u06f1\u06f4\u06f0\u06f5/\u06f0\u06f4/\u06f1\u06f3 \u062a\u0627 \u06f1\u06f4\u06f0\u06f5/\u06f0\u06f5/\u06f1\u06f2``"""
        last_day = (self.end - timedelta(seconds=1)).date()
        return f"{jalali_date_fa(self.start.date())} \u062a\u0627 {jalali_date_fa(last_day)}"

    def duration_fa(self) -> str:
        return f"{fa_digits(self.days)} \u0631\u0648\u0632"


def _midnight(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _bucket_start(moment: datetime, granularity: Granularity) -> datetime:
    base = _midnight(moment)
    if granularity is Granularity.DAY:
        return base
    if granularity is Granularity.WEEK:
        # Saturday is the first day of the Iranian week.
        offset = (base.weekday() - 5) % 7
        return base - timedelta(days=offset)
    return base.replace(day=1)


def _advance(moment: datetime, granularity: Granularity) -> datetime:
    if granularity is Granularity.DAY:
        return moment + timedelta(days=1)
    if granularity is Granularity.WEEK:
        return moment + timedelta(days=7)
    if moment.month == 12:
        return moment.replace(year=moment.year + 1, month=1)
    return moment.replace(month=moment.month + 1)


def bucket_label_fa(moment: datetime, granularity: Granularity) -> str:
    """The Jalali label for one bucket on a chart axis."""
    if granularity is Granularity.MONTH:
        return jalali_month_label(moment.date())
    return jalali_day_label(moment.date())


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_date(moment: datetime) -> date:
    return moment.date()


__all__ = [
    "MAX_RANGE_DAYS",
    "PRESET_DAYS",
    "DateRange",
    "as_date",
    "bucket_label_fa",
    "utc_now",
]
