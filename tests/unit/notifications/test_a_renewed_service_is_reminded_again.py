"""A customer who renewed is reminded before the new term ends too.

A reminder's dedupe key was the service and the mark - `expiry:<id>:3` - and
dedupe is permanent. A renewal extends the same service, so after the first
term every one of those keys was already used: a customer who renewed once
was never again told their service was about to end, nor that they had used
80% of their traffic. Those are the customers most worth reminding.

The key now carries the term's end date. Within one term each reminder still
goes out once; a new term, with a new end, has reminders of its own.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest

from tests.unit.notifications.fakes import EPOCH, subscription
from tests.unit.notifications.world import World

pytestmark = pytest.mark.unit


def _keys(w: World) -> list[str]:
    return [n.message.key for n in w.stored()]


def test_the_three_day_reminder_comes_again_after_a_renewal() -> None:
    w = World()
    first_term = subscription(days_from=3, now=EPOCH)
    w.subscriptions.snapshots = [first_term]
    w.reminders.run_expiration_reminders()

    # Renewed: the same service, thirty days further on, and a month later
    # it is three days from its new end.
    renewed = replace(first_term, expires_at=first_term.expires_at + timedelta(days=30))
    w.subscriptions.snapshots = [renewed]
    w.clock.advance(days=30)
    report = w.reminders.run_expiration_reminders()

    assert report.queued == 1
    assert _keys(w) == ["expiry.soon", "expiry.soon"]


def test_within_one_term_the_reminder_is_still_sent_once() -> None:
    w = World()
    w.subscriptions.snapshots = [subscription(days_from=3, now=EPOCH)]
    w.reminders.run_expiration_reminders()
    w.clock.advance(hours=6)

    second = w.reminders.run_expiration_reminders()

    assert second.queued == 0


def test_the_traffic_warning_comes_again_after_a_renewal() -> None:
    w = World()
    first_term = subscription(days_from=20, used_gib=85.0, total_gib=100.0, now=EPOCH)
    w.subscriptions.snapshots = [first_term]
    w.reminders.run_traffic_reminders()

    renewed = replace(
        first_term, expires_at=first_term.expires_at + timedelta(days=30), used_gib=85.0
    )
    w.subscriptions.snapshots = [renewed]
    report = w.reminders.run_traffic_reminders()

    assert report.queued == 1
