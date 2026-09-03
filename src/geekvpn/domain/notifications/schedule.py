"""Scheduled job bookkeeping and reminder thresholds.

The thresholds live in the domain rather than in the job code so that both the
reminder sweep and its tests read the same numbers, and so that a dedupe key
can be derived from a threshold deterministically.

Dedupe is the whole trick of reminders. A sweep that runs hourly must not send
the "3 days left" warning twelve times; the key ``expiry:sub-7:3`` is recorded
on first send and checked on every subsequent pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from geekvpn.domain.notifications.enums import JobKind

# Warn at these remaining-day marks. Descending so the sweep picks the most
# urgent applicable one first.
EXPIRY_REMINDER_DAYS: tuple[int, ...] = (7, 3, 1)

# Warn once the plan is this percent consumed.
TRAFFIC_THRESHOLDS: tuple[int, ...] = (80, 95)

# Percent at which the plan counts as finished rather than merely low.
TRAFFIC_EXHAUSTED_PERCENT = 100

#: Silence long enough to be worth asking about. Short enough that a
#: customer who cannot connect hears from us while they still care, long
#: enough that a weekend away does not trigger it.
IDLE_NUDGE_DAYS = 3

DEFAULT_INTERVALS: dict[JobKind, int] = {
    JobKind.EXPIRATION_REMINDER: 60,
    JobKind.TRAFFIC_REMINDER: 30,
    JobKind.IDLE_NUDGE: 360,
    JobKind.BROADCAST_DISPATCH: 1,
    JobKind.CAMPAIGN_ANNOUNCE: 60,
    JobKind.DEFERRED_FLUSH: 15,
}


def expiry_dedupe_key(subscription_id: str, days_left: int) -> str:
    return f"expiry:{subscription_id}:{days_left}"


def traffic_dedupe_key(subscription_id: str, threshold: int) -> str:
    return f"traffic:{subscription_id}:{threshold}"


def idle_dedupe_key(subscription_id: str, since: str) -> str:
    """One nudge per spell of silence, not one every sweep.

    Keyed on when the silence started, so a customer who reconnects and
    then goes quiet again is a new spell and hears from us again - while
    somebody who stays away for a month is asked exactly once.
    """
    return f"idle:{subscription_id}:{since}"


def broadcast_dedupe_key(broadcast_id: str, user_id: int) -> str:
    return f"broadcast:{broadcast_id}:{user_id}"


def campaign_dedupe_key(campaign_id: str, user_id: int) -> str:
    return f"campaign:{campaign_id}:{user_id}"


def expiry_threshold_for(days_left: int) -> int | None:
    """The threshold a given remaining-days value triggers, if any.

    Exact matching is deliberate. A sweep that fired for "<= 7" would warn
    every single day from day seven onward, and the dedupe key would not save
    us because each day is a different key.
    """
    return days_left if days_left in EXPIRY_REMINDER_DAYS else None


def traffic_threshold_for(percent_used: float) -> int | None:
    """The highest crossed traffic threshold, or None below the lowest.

    Highest-first means a customer who jumps from 50% to 97% in one sweep gets
    the 95% warning, not a stale 80% one.
    """
    for threshold in sorted(TRAFFIC_THRESHOLDS, reverse=True):
        if percent_used >= threshold:
            return threshold
    return None


@dataclass(slots=True)
class ScheduleEntry:
    """One recurring job and when it last ran.

    Mutable on purpose: the scheduler owns these and stamps them in place
    after each run.
    """

    job: JobKind
    interval_minutes: int
    last_run_at: datetime | None = None
    enabled: bool = True

    @classmethod
    def for_job(cls, job: JobKind) -> ScheduleEntry:
        return cls(job=job, interval_minutes=DEFAULT_INTERVALS[job])

    def next_run_at(self) -> datetime | None:
        if self.last_run_at is None:
            return None
        return self.last_run_at + timedelta(minutes=self.interval_minutes)

    def is_due(self, now: datetime) -> bool:
        """A job that has never run is due immediately."""
        if not self.enabled:
            return False
        due_at = self.next_run_at()
        return due_at is None or due_at <= now

    def mark_ran(self, now: datetime) -> None:
        self.last_run_at = now


def default_schedule() -> list[ScheduleEntry]:
    return [ScheduleEntry.for_job(job) for job in DEFAULT_INTERVALS]


def due_entries(entries: list[ScheduleEntry], now: datetime) -> list[ScheduleEntry]:
    return [entry for entry in entries if entry.is_due(now)]


__all__ = [
    "DEFAULT_INTERVALS",
    "EXPIRY_REMINDER_DAYS",
    "IDLE_NUDGE_DAYS",
    "TRAFFIC_EXHAUSTED_PERCENT",
    "TRAFFIC_THRESHOLDS",
    "ScheduleEntry",
    "broadcast_dedupe_key",
    "campaign_dedupe_key",
    "default_schedule",
    "due_entries",
    "expiry_dedupe_key",
    "expiry_threshold_for",
    "idle_dedupe_key",
    "traffic_dedupe_key",
    "traffic_threshold_for",
]
