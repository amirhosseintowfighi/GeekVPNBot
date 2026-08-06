"""The job runner."""

from __future__ import annotations

from geekvpn.domain.notifications.enums import JobKind
from geekvpn.domain.notifications.schedule import (
    DEFAULT_INTERVALS,
    ScheduleEntry,
    default_schedule,
    due_entries,
)
from tests.unit.notifications.fakes import EPOCH
from tests.unit.notifications.world import World


def test_default_schedule_covers_every_job_kind():
    jobs = {entry.job for entry in default_schedule()}
    assert jobs == set(JobKind)


def test_every_job_has_a_positive_interval():
    for job in JobKind:
        assert DEFAULT_INTERVALS[job] > 0


def test_a_job_that_never_ran_is_due_immediately():
    """A fresh deployment must not wait an hour for the first sweep."""
    entry = ScheduleEntry.for_job(JobKind.EXPIRATION_REMINDER)
    assert entry.last_run_at is None
    assert entry.is_due(EPOCH)


def test_a_job_is_not_due_again_until_its_interval_passes():
    entry = ScheduleEntry.for_job(JobKind.TRAFFIC_REMINDER)
    entry.mark_ran(EPOCH)
    assert not entry.is_due(EPOCH)
    later = entry.next_run_at()
    assert later is not None
    assert entry.is_due(later)


def test_a_disabled_job_is_never_due():
    entry = ScheduleEntry.for_job(JobKind.CAMPAIGN_ANNOUNCE)
    entry.enabled = False
    assert not entry.is_due(EPOCH)


def test_due_entries_filters_the_table():
    entries = default_schedule()
    for entry in entries:
        entry.mark_ran(EPOCH)
    entries[0].enabled = True
    entries[0].last_run_at = None
    due = due_entries(entries, EPOCH)
    assert [e.job for e in due] == [entries[0].job]


def test_only_registered_jobs_are_reported_due():
    w = World()
    assert w.scheduler.due_jobs() == ()
    w.scheduler.register(JobKind.EXPIRATION_REMINDER, lambda: None)
    assert w.scheduler.due_jobs() == (JobKind.EXPIRATION_REMINDER,)


def test_tick_runs_a_due_job_once_then_waits():
    w = World()
    calls = []
    w.scheduler.register(JobKind.TRAFFIC_REMINDER, lambda: calls.append(1))
    w.scheduler.tick()
    w.scheduler.tick()
    assert len(calls) == 1


def test_tick_runs_again_after_the_interval():
    w = World()
    calls = []
    w.scheduler.register(JobKind.TRAFFIC_REMINDER, lambda: calls.append(1))
    w.scheduler.tick()
    w.clock.advance(minutes=DEFAULT_INTERVALS[JobKind.TRAFFIC_REMINDER] + 1)
    w.scheduler.tick()
    assert len(calls) == 2


def test_a_failing_job_does_not_stop_the_others():
    w = World()
    ran = []

    def boom():
        raise RuntimeError("panel down")

    w.scheduler.register(JobKind.EXPIRATION_REMINDER, boom)
    w.scheduler.register(JobKind.TRAFFIC_REMINDER, lambda: ran.append(1))
    report = w.scheduler.tick()
    assert ran == [1]
    assert len(report.failures()) == 1
    assert report.failures()[0].error == "RuntimeError"
    assert not report.healthy()


def test_a_permanently_failing_job_is_not_retried_on_every_tick():
    """Stamping the entry before running is what stops the hot loop."""
    w = World()
    attempts = []

    def boom():
        attempts.append(1)
        raise RuntimeError("still down")

    w.scheduler.register(JobKind.EXPIRATION_REMINDER, boom)
    w.scheduler.tick()
    w.scheduler.tick()
    w.scheduler.tick()
    assert len(attempts) == 1


def test_tick_reports_the_jobs_it_skipped():
    w = World()
    w.scheduler.register(JobKind.TRAFFIC_REMINDER, lambda: None)
    w.scheduler.tick()
    report = w.scheduler.tick()
    assert report.ran() == []
    assert len(report.runs) == 1


def test_run_now_ignores_the_interval():
    """The admin panel's manual-run button."""
    w = World()
    calls = []
    w.scheduler.register(JobKind.DEFERRED_FLUSH, lambda: calls.append(1))
    w.scheduler.tick()
    run = w.scheduler.run_now(JobKind.DEFERRED_FLUSH)
    assert run.ran and run.ok
    assert len(calls) == 2


def test_run_now_on_an_unregistered_job_is_reported_not_raised():
    w = World()
    run = w.scheduler.run_now(JobKind.BROADCAST_DISPATCH)
    assert not run.ran
    assert run.error == "no_handler"


def test_run_now_captures_a_handler_failure():
    w = World()

    def boom():
        raise ValueError("bad segment")

    w.scheduler.register(JobKind.BROADCAST_DISPATCH, boom)
    run = w.scheduler.run_now(JobKind.BROADCAST_DISPATCH)
    assert run.ran and not run.ok
    assert run.error == "ValueError"


def test_an_operator_can_silence_one_sweep():
    w = World()
    calls = []
    w.scheduler.register(JobKind.CAMPAIGN_ANNOUNCE, lambda: calls.append(1))
    w.scheduler.enable(JobKind.CAMPAIGN_ANNOUNCE, False)
    w.scheduler.tick()
    assert calls == []


def test_intervals_are_adjustable_at_runtime():
    w = World()
    w.scheduler.set_interval(JobKind.DEFERRED_FLUSH, 5)
    assert w.scheduler.entry_for(JobKind.DEFERRED_FLUSH).interval_minutes == 5


def test_a_nonsense_interval_is_ignored():
    w = World()
    before = w.scheduler.entry_for(JobKind.DEFERRED_FLUSH).interval_minutes
    w.scheduler.set_interval(JobKind.DEFERRED_FLUSH, 0)
    assert w.scheduler.entry_for(JobKind.DEFERRED_FLUSH).interval_minutes == before


def test_the_whole_engine_runs_from_one_tick():
    """End to end: a wired scheduler produces real notifications."""
    from tests.unit.notifications.fakes import subscription

    w = World()
    w.subscriptions.snapshots = [subscription(days_from=3, now=EPOCH)]
    w.scheduler.register(JobKind.EXPIRATION_REMINDER, w.reminders.run_expiration_reminders)
    w.scheduler.register(JobKind.TRAFFIC_REMINDER, w.reminders.run_traffic_reminders)
    w.scheduler.register(JobKind.BROADCAST_DISPATCH, w.broadcasts.dispatch_due)
    w.scheduler.register(JobKind.CAMPAIGN_ANNOUNCE, w.campaigns.run_pending_announcements)
    w.scheduler.register(JobKind.DEFERRED_FLUSH, w.engine.flush_deferred)

    report = w.scheduler.tick()
    assert report.healthy()
    assert len(report.ran()) == 5
    assert len(w.stored()) == 1
