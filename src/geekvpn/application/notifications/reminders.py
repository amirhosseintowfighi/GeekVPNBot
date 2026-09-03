"""Expiration and traffic reminder sweeps.

Both jobs share one shape: scan a read model, decide whether this subscription
has crossed a threshold, and ask the engine to notify with a *deterministic
dedupe key*. The key is what makes an hourly sweep safe -- without it, a
customer three days from expiry would be told so twenty-four times.

The jobs never build Persian copy and never touch preferences; both belong to
the engine. They only decide *who* has crossed *what*.
"""

from __future__ import annotations

from dataclasses import dataclass

from geekvpn.application.notifications.engine import NotificationEngine
from geekvpn.application.notifications.ports import (
    Clock,
    EventPublisher,
    SubscriptionReader,
    SubscriptionSnapshot,
)
from geekvpn.domain.notifications.enums import JobKind
from geekvpn.domain.notifications.events import ReminderJobCompleted
from geekvpn.domain.notifications.message import fa_gib
from geekvpn.domain.notifications.schedule import (
    EXPIRY_REMINDER_DAYS,
    IDLE_NUDGE_DAYS,
    TRAFFIC_EXHAUSTED_PERCENT,
    TRAFFIC_THRESHOLDS,
    expiry_dedupe_key,
    expiry_threshold_for,
    idle_dedupe_key,
    traffic_dedupe_key,
    traffic_threshold_for,
)


@dataclass(frozen=True, slots=True)
class SweepReport:
    """What one run of a reminder job did.

    ``skipped`` counts subscriptions that were examined and deliberately left
    alone -- not at a threshold, already warned, unmetered. Keeping it
    separate from ``queued`` is what makes a quiet job distinguishable from a
    broken one.
    """

    job: JobKind
    examined: int = 0
    queued: int = 0
    skipped: int = 0

    def with_queued(self) -> SweepReport:
        return SweepReport(
            job=self.job,
            examined=self.examined + 1,
            queued=self.queued + 1,
            skipped=self.skipped,
        )

    def with_skipped(self) -> SweepReport:
        return SweepReport(
            job=self.job,
            examined=self.examined + 1,
            queued=self.queued,
            skipped=self.skipped + 1,
        )


class ReminderService:
    """The two recurring customer-facing sweeps."""

    def __init__(
        self,
        *,
        engine: NotificationEngine,
        subscriptions: SubscriptionReader,
        clock: Clock,
        events: EventPublisher,
    ) -> None:
        self._engine = engine
        self._subscriptions = subscriptions
        self._clock = clock
        self._events = events


    # ---- Silence --------------------------------------------------------

    def run_idle_nudges(self) -> SweepReport:
        """Ask the customers who have a working service and are not using it.

        Three days of no traffic on an account that still has both time and
        quota left is the shape of somebody who cannot connect: a blocked
        server, a wrong app, a stale link. They rarely open a ticket about it -
        they assume it is broken and leave - so this is us asking first.

        The dedupe key is the start of the silence, so one spell of quiet
        earns exactly one message however many times the sweep runs, and a
        customer who comes back and goes quiet again is asked again.
        """
        now = self._clock.now()
        report = SweepReport(job=JobKind.IDLE_NUDGE)

        for snapshot in self._subscriptions.idle_since(IDLE_NUDGE_DAYS, now=now):
            if not snapshot.active:
                report = report.with_skipped()
                continue

            since = snapshot.last_used_at or snapshot.started_at
            if since is None:
                # No idea when the silence began, so no stable dedupe key: a
                # message here would repeat on every single sweep.
                report = report.with_skipped()
                continue

            result = self._engine.notify(
                user_id=snapshot.user_id,
                template_key="service.idle",
                fields={"plan": snapshot.plan_name, "days": IDLE_NUDGE_DAYS},
                dedupe_key=idle_dedupe_key(snapshot.subscription_id, since.date().isoformat()),
                source=str(JobKind.IDLE_NUDGE),
            )
            report = report.with_queued() if result.was_queued else report.with_skipped()

        self._events.publish_all(
            [
                ReminderJobCompleted(
                    job=report.job,
                    examined=report.examined,
                    queued=report.queued,
                    skipped=report.skipped,
                )
            ]
        )
        return report

    # ---- Expiration -----------------------------------------------------

    def run_expiration_reminders(self) -> SweepReport:
        """Warn at 7, 3 and 1 days out, and once on the day it dies.

        Exact-day matching, not "<= 7", so each customer gets three warnings
        rather than seven.
        """
        now = self._clock.now()
        report = SweepReport(job=JobKind.EXPIRATION_REMINDER)
        widest = max(EXPIRY_REMINDER_DAYS)

        for snapshot in self._subscriptions.expiring_within(widest, now=now):
            if not snapshot.active:
                report = report.with_skipped()
                continue

            days = snapshot.days_left(now)

            if days <= 0:
                if self._notify_expired(snapshot):
                    report = report.with_queued()
                else:
                    report = report.with_skipped()
                continue

            threshold = expiry_threshold_for(days)
            if threshold is None:
                report = report.with_skipped()
                continue

            key = "expiry.today" if threshold == 1 else "expiry.soon"
            fields = (
                {"plan": snapshot.plan_name}
                if threshold == 1
                else {"plan": snapshot.plan_name, "days": threshold}
            )
            result = self._engine.notify(
                user_id=snapshot.user_id,
                template_key=key,
                fields=fields,
                dedupe_key=expiry_dedupe_key(snapshot.subscription_id, threshold),
                source=str(JobKind.EXPIRATION_REMINDER),
            )
            report = report.with_queued() if result.was_queued else report.with_skipped()

        self._events.publish_all(
            [
                ReminderJobCompleted(
                    job=report.job,
                    examined=report.examined,
                    queued=report.queued,
                    skipped=report.skipped,
                )
            ]
        )
        return report

    def _notify_expired(self, snapshot: SubscriptionSnapshot) -> bool:
        result = self._engine.notify(
            user_id=snapshot.user_id,
            template_key="expiry.expired",
            fields={"plan": snapshot.plan_name},
            dedupe_key=expiry_dedupe_key(snapshot.subscription_id, 0),
            source=str(JobKind.EXPIRATION_REMINDER),
        )
        return result.was_queued

    # ---- Traffic --------------------------------------------------------

    def run_traffic_reminders(self) -> SweepReport:
        """Warn at 80% and 95%, and separately when the plan is finished.

        Unmetered plans are skipped rather than treated as zero-capacity,
        which would otherwise warn every unlimited customer immediately.
        """
        now = self._clock.now()
        report = SweepReport(job=JobKind.TRAFFIC_REMINDER)
        floor = float(min(TRAFFIC_THRESHOLDS))

        for snapshot in self._subscriptions.with_traffic_usage(min_percent=floor, now=now):
            if not snapshot.active:
                report = report.with_skipped()
                continue

            percent = snapshot.percent_used()
            if percent is None:
                report = report.with_skipped()
                continue

            if percent >= TRAFFIC_EXHAUSTED_PERCENT:
                result = self._engine.notify(
                    user_id=snapshot.user_id,
                    template_key="traffic.exhausted",
                    fields={"plan": snapshot.plan_name},
                    dedupe_key=traffic_dedupe_key(
                        snapshot.subscription_id, TRAFFIC_EXHAUSTED_PERCENT
                    ),
                    source=str(JobKind.TRAFFIC_REMINDER),
                )
                report = report.with_queued() if result.was_queued else report.with_skipped()
                continue

            threshold = traffic_threshold_for(percent)
            if threshold is None:
                report = report.with_skipped()
                continue

            result = self._engine.notify(
                user_id=snapshot.user_id,
                template_key="traffic.warning",
                fields={
                    "plan": snapshot.plan_name,
                    "percent": threshold,
                    "remaining": fa_gib(snapshot.remaining_gib()),
                },
                dedupe_key=traffic_dedupe_key(snapshot.subscription_id, threshold),
                source=str(JobKind.TRAFFIC_REMINDER),
            )
            report = report.with_queued() if result.was_queued else report.with_skipped()

        self._events.publish_all(
            [
                ReminderJobCompleted(
                    job=report.job,
                    examined=report.examined,
                    queued=report.queued,
                    skipped=report.skipped,
                )
            ]
        )
        return report


__all__ = ["ReminderService", "SweepReport"]
