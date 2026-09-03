"""Asking the customer who has a working service and is not using it.

Three days of no traffic on an account that still has both time and quota left
is the shape of somebody who cannot connect. They rarely open a ticket about it
- they assume it is broken and leave - so the bot asks first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.notifications.ports import SubscriptionSnapshot
from geekvpn.application.notifications.reminders import ReminderService
from geekvpn.domain.notifications.enums import JobKind
from geekvpn.domain.notifications.schedule import IDLE_NUDGE_HOURS, idle_dedupe_key

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)


@dataclass
class _Result:
    was_queued: bool = True


class FakeEngine:
    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.seen_keys: set[str] = set()

    def notify(self, **kwargs) -> _Result:
        # Mirrors the real engine's dedupe: a repeated key is not sent again.
        key = kwargs["dedupe_key"]
        if key in self.seen_keys:
            return _Result(was_queued=False)
        self.seen_keys.add(key)
        self.sent.append(kwargs)
        return _Result()


class FakeReader:
    def __init__(self, rows: list[SubscriptionSnapshot]) -> None:
        self.rows = rows
        self.asked_hours: int | None = None

    def expiring_within(self, days, *, now):
        return []

    def with_traffic_usage(self, *, min_percent, now):
        return []

    def idle_since(self, hours, *, now):
        self.asked_hours = hours
        return self.rows


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeEvents:
    def __init__(self) -> None:
        self.published: list = []

    def publish_all(self, events) -> None:
        self.published.extend(events)


def _snapshot(**kwargs) -> SubscriptionSnapshot:
    base = {
        "subscription_id": "sub-1",
        "user_id": 7,
        "plan_name": "پایه",
        "expires_at": NOW + timedelta(days=20),
        "used_gib": 1.0,
        "total_gib": 50.0,
        "active": True,
        "last_connected_at": NOW - timedelta(days=5),
        "last_used_at": NOW - timedelta(days=5),
        "started_at": NOW - timedelta(days=30),
    }
    base.update(kwargs)
    return SubscriptionSnapshot(**base)  # type: ignore[arg-type]


def _service(rows: list[SubscriptionSnapshot]) -> tuple[ReminderService, FakeEngine, FakeReader]:
    engine = FakeEngine()
    reader = FakeReader(rows)
    service = ReminderService(
        engine=engine,
        subscriptions=reader,
        clock=FixedClock(),
        events=FakeEvents(),
    )
    return service, engine, reader


def test_a_quiet_customer_is_asked_what_went_wrong():
    service, engine, _ = _service([_snapshot()])

    report = service.run_idle_nudges()

    assert report.queued == 1
    assert engine.sent[0]["template_key"] == "service.idle"
    assert engine.sent[0]["user_id"] == 7


def test_the_same_silence_is_only_asked_about_once():
    """Otherwise a customer away for a month is nagged every six hours."""
    service, engine, _ = _service([_snapshot(), _snapshot()])

    service.run_idle_nudges()

    assert len(engine.sent) == 1


def test_coming_back_and_going_quiet_again_earns_a_second_message():
    """The dedupe is on when the silence began, not on the subscription."""
    first = idle_dedupe_key("sub-1", (NOW - timedelta(days=5)).date().isoformat())
    second = idle_dedupe_key("sub-1", (NOW - timedelta(days=40)).date().isoformat())

    assert first != second


def test_a_cancelled_service_is_left_alone():
    service, engine, _ = _service([_snapshot(active=False)])

    report = service.run_idle_nudges()

    assert engine.sent == []
    assert report.skipped == 1


def test_a_row_with_no_history_at_all_is_skipped():
    """No date means no stable dedupe key, and a message would repeat on every
    single sweep."""
    service, engine, _ = _service([_snapshot(last_connected_at=None, started_at=None)])

    service.run_idle_nudges()

    assert engine.sent == []


def test_the_sweep_asks_for_exactly_seventy_two_hours():
    """Counted in hours, not days. "3 days" is the kind of thing that gets
    rounded to a date somewhere down the stack."""
    service, _, reader = _service([])

    service.run_idle_nudges()

    assert reader.asked_hours == 72
    assert IDLE_NUDGE_HOURS == 72


def test_the_report_names_its_own_job():
    service, _, _ = _service([])

    assert service.run_idle_nudges().job is JobKind.IDLE_NUDGE
