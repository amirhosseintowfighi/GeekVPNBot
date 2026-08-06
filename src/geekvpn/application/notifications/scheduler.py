"""The scheduled-job runner.

A deliberately small, dependency-free scheduler: the deployment ticks it (cron,
a loop, a worker) and it decides which jobs are due. Keeping the decision here
rather than in crontab means the intervals are testable and the same code runs
in every environment.

Every job is wrapped: one failing sweep records its error and the remaining
jobs still run. A traffic-reminder bug must not also stop broadcasts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from geekvpn.application.notifications.ports import Clock
from geekvpn.domain.notifications.enums import JobKind
from geekvpn.domain.notifications.schedule import ScheduleEntry, default_schedule


@dataclass(frozen=True, slots=True)
class JobRun:
    """One job's outcome in one tick."""

    job: JobKind
    ran: bool
    ok: bool = True
    error: str = ""
    detail: object = None
    at: datetime | None = None


@dataclass(slots=True)
class TickReport:
    at: datetime
    runs: list[JobRun] = field(default_factory=list)

    def ran(self) -> list[JobRun]:
        return [run for run in self.runs if run.ran]

    def failures(self) -> list[JobRun]:
        return [run for run in self.runs if run.ran and not run.ok]

    def healthy(self) -> bool:
        return not self.failures()


class NotificationScheduler:
    """Owns the schedule table and runs whatever is due."""

    def __init__(
        self,
        *,
        clock: Clock,
        entries: list[ScheduleEntry] | None = None,
    ) -> None:
        self._clock = clock
        self._entries: list[ScheduleEntry] = entries or default_schedule()
        self._handlers: dict[JobKind, Callable[[], object]] = {}

    # ---- Registration ---------------------------------------------------

    def register(self, job: JobKind, handler: Callable[[], object]) -> None:
        self._handlers[job] = handler

    def entries(self) -> tuple[ScheduleEntry, ...]:
        return tuple(self._entries)

    def entry_for(self, job: JobKind) -> ScheduleEntry | None:
        for entry in self._entries:
            if entry.job is job:
                return entry
        return None

    def enable(self, job: JobKind, enabled: bool = True) -> None:
        """Lets an operator silence one sweep without a deploy."""
        entry = self.entry_for(job)
        if entry is not None:
            entry.enabled = enabled

    def set_interval(self, job: JobKind, minutes: int) -> None:
        entry = self.entry_for(job)
        if entry is not None and minutes > 0:
            entry.interval_minutes = minutes

    def due_jobs(self, now: datetime | None = None) -> tuple[JobKind, ...]:
        moment = now or self._clock.now()
        return tuple(
            entry.job
            for entry in self._entries
            if entry.is_due(moment) and entry.job in self._handlers
        )

    # ---- Execution ------------------------------------------------------

    def tick(self) -> TickReport:
        """Run every due job once.

        The entry is stamped even when the handler raises. A job that fails
        every time must not be retried on every tick -- that turns one bug
        into a hot loop against Telegram.
        """
        now = self._clock.now()
        report = TickReport(at=now)

        for entry in self._entries:
            handler = self._handlers.get(entry.job)
            if handler is None:
                continue
            if not entry.is_due(now):
                report.runs.append(JobRun(job=entry.job, ran=False, at=now))
                continue

            entry.mark_ran(now)
            try:
                detail = handler()
            except Exception as exc:
                report.runs.append(
                    JobRun(
                        job=entry.job,
                        ran=True,
                        ok=False,
                        error=type(exc).__name__,
                        at=now,
                    )
                )
                continue

            report.runs.append(JobRun(job=entry.job, ran=True, ok=True, detail=detail, at=now))

        return report

    def run_now(self, job: JobKind) -> JobRun:
        """Force one job immediately, ignoring its interval.

        This is the admin panel's \u0627\u062c\u0631\u0627\u06cc \u062f\u0633\u062a\u06cc button.
        """
        now = self._clock.now()
        handler = self._handlers.get(job)
        if handler is None:
            return JobRun(job=job, ran=False, ok=False, error="no_handler", at=now)
        entry = self.entry_for(job)
        if entry is not None:
            entry.mark_ran(now)
        try:
            detail = handler()
        except Exception as exc:
            return JobRun(job=job, ran=True, ok=False, error=type(exc).__name__, at=now)
        return JobRun(job=job, ran=True, ok=True, detail=detail, at=now)


__all__ = ["JobRun", "NotificationScheduler", "TickReport"]
