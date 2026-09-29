"""Per-day traffic for one service, built from the panel readings.

Panels report one absolute total per account, so the platform keeps the last
reading of each (Tehran) day and a day's traffic is the difference from the
day before. Reading it back is pure and lives here; storage is a port.

A total that goes *down* means the panel reset the counter (a renewal with a
fresh quota), so that day counts everything read since the reset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Protocol

#: Iran has had no daylight saving since 2022; a fixed offset is exact.
TEHRAN = timezone(timedelta(hours=3, minutes=30))

#: Longest window the app asks for; older rows are dropped.
KEEP_DAYS = 62


def tehran_day(at: datetime) -> date:
    aware = at if at.tzinfo else at.replace(tzinfo=UTC)
    return aware.astimezone(TEHRAN).date()


@dataclass(frozen=True, slots=True)
class DayUsage:
    day: date
    used_mib: int


class UsageHistory(Protocol):
    async def record(self, subscription_id: str, day: date, used_mib: int) -> None:
        """The day's latest absolute reading (upsert)."""

    async def readings(self, subscription_id: str, since: date) -> list[DayUsage]:
        """Stored readings from `since` on, oldest first."""


def daily_usage(readings: list[DayUsage], *, today: date, days: int) -> list[DayUsage]:
    """`days` entries ending today, each the traffic used on that day.

    `readings` may start before the window (the day before the first shown
    day is what its difference is measured from) and may skip days: a day
    without a reading used nothing that anyone saw, and the traffic shows on
    the next day that has one.
    """
    first = today - timedelta(days=days - 1)
    ordered = sorted(readings, key=lambda r: r.day)
    by_day: dict[date, int] = {}
    previous: int | None = None
    for reading in ordered:
        if reading.day > today:
            break
        if previous is None:
            # Nothing before it: the first reading on record is a baseline.
            # Counting it would put a service's whole past on the day the
            # history started.
            used = 0
        elif reading.used_mib >= previous:
            used = reading.used_mib - previous
        else:
            used = reading.used_mib
        previous = reading.used_mib
        if reading.day >= first:
            by_day[reading.day] = used
    return [
        DayUsage(first + timedelta(days=i), by_day.get(first + timedelta(days=i), 0))
        for i in range(days)
    ]


__all__ = ["KEEP_DAYS", "TEHRAN", "DayUsage", "UsageHistory", "daily_usage", "tehran_day"]
