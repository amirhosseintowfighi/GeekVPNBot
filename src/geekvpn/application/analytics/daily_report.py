"""The operators' daily orders report.

One message a day in the bot: how many orders came in yesterday, how many of
them turned into a working service, how many are stuck between money and
service, and what the day took in. The dashboard has the same numbers, but
only for someone who opens it; a report that arrives is one that gets read.

Yesterday, not today: a report sent at midnight about a day still running is
a half-day's figures, and one sent the morning after needs a worker that was
up at midnight. Reporting the day that just ended, on the first tick after
it ends, gives whole days and survives a restart - the last day reported is
remembered, so a worker that was down at midnight sends it when it is back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Protocol

#: The shop's day. Fixed offset: Iran has not observed daylight saving since
#: 2022, and the rest of the platform reads it the same way.
TEHRAN = timezone(timedelta(hours=3, minutes=30))


@dataclass(frozen=True, slots=True)
class DayOrders:
    """One day's orders, counted by what became of them."""

    day: date
    #: Orders placed that day.
    placed: int = 0
    #: ... of which a service is running.
    delivered: int = 0
    #: ... paid, still without a service: the queue a human should look at.
    waiting: int = 0
    #: ... paid, and the panel refused the service.
    failed: int = 0
    #: ... never paid, or cancelled.
    unpaid: int = 0
    #: ... paid and refunded.
    refunded: int = 0
    #: Money taken that day, in toman: orders paid that day and not refunded.
    revenue: int = 0
    #: Of the orders paid that day, how many extended a service.
    renewals: int = 0
    #: Customers who first started the bot that day.
    new_customers: int = 0

    @property
    def paid(self) -> int:
        """Placed that day and paid for, whatever became of it after."""
        return self.delivered + self.waiting + self.failed + self.refunded

    @property
    def success_percent(self) -> int | None:
        """Paid orders that became a working service. None with nothing paid."""
        if self.paid == 0:
            return None
        return round(self.delivered * 100 / self.paid)

    @property
    def payment_percent(self) -> int | None:
        """Placed orders that were paid for. None with nothing placed."""
        if self.placed == 0:
            return None
        return round(self.paid * 100 / self.placed)


class DayOrdersReader(Protocol):
    async def day(self, day: date, *, start: datetime, end: datetime) -> DayOrders:
        """The figures for [start, end), labelled with `day`."""
        ...


def bounds(day: date) -> tuple[datetime, datetime]:
    """The shop's day in UTC, as a half-open range."""
    start = datetime.combine(day, time.min, tzinfo=TEHRAN)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def day_to_report(now: datetime, last_reported: date | None) -> date | None:
    """The day to report now, or None when it has already been sent."""
    yesterday = now.astimezone(TEHRAN).date() - timedelta(days=1)
    if last_reported is not None and last_reported >= yesterday:
        return None
    return yesterday
