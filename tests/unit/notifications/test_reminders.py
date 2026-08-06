"""Expiration and traffic sweeps."""

from __future__ import annotations

from geekvpn.domain.notifications.events import ReminderJobCompleted
from geekvpn.domain.notifications.schedule import (
    expiry_threshold_for,
    traffic_threshold_for,
)
from tests.unit.notifications.fakes import EPOCH, USER_ID, subscription
from tests.unit.notifications.world import World


def _bodies(w: World) -> list[str]:
    return [n.message.key for n in w.stored()]


def test_expiry_thresholds_match_exactly():
    assert expiry_threshold_for(7) == 7
    assert expiry_threshold_for(3) == 3
    assert expiry_threshold_for(1) == 1
    assert expiry_threshold_for(5) is None
    assert expiry_threshold_for(0) is None


def test_traffic_threshold_picks_the_highest_crossed():
    assert traffic_threshold_for(79) is None
    assert traffic_threshold_for(80) == 80
    assert traffic_threshold_for(94) == 80
    assert traffic_threshold_for(97) == 95


def test_seven_day_reminder_is_queued():
    w = World()
    w.subscriptions.snapshots = [subscription(days_from=7, now=EPOCH)]
    report = w.reminders.run_expiration_reminders()
    assert report.queued == 1
    assert _bodies(w) == ["expiry.soon"]


def test_five_days_out_is_silence():
    """Reminders on arbitrary days train customers to ignore them."""
    w = World()
    w.subscriptions.snapshots = [subscription(days_from=5, now=EPOCH)]
    report = w.reminders.run_expiration_reminders()
    assert report.queued == 0
    assert report.skipped == 1


def test_last_day_uses_the_urgent_template():
    w = World()
    w.subscriptions.snapshots = [subscription(days_from=1, now=EPOCH)]
    w.reminders.run_expiration_reminders()
    assert _bodies(w) == ["expiry.today"]


def test_an_already_expired_service_gets_the_expired_notice():
    w = World()
    w.subscriptions.snapshots = [subscription(days_from=-2, now=EPOCH)]
    w.reminders.run_expiration_reminders()
    assert _bodies(w) == ["expiry.expired"]


def test_running_the_sweep_twice_notifies_once():
    """The job runs hourly; dedupe is the only thing stopping a flood."""
    w = World()
    w.subscriptions.snapshots = [subscription(days_from=3, now=EPOCH)]
    w.reminders.run_expiration_reminders()
    second = w.reminders.run_expiration_reminders()
    assert second.queued == 0
    assert len(w.stored()) == 1


def test_crossing_into_a_new_threshold_notifies_again():
    w = World()
    w.subscriptions.snapshots = [subscription(days_from=7, now=EPOCH)]
    w.reminders.run_expiration_reminders()
    w.clock.advance(days=4)
    report = w.reminders.run_expiration_reminders()
    assert report.queued == 1
    assert len(w.stored()) == 2


def test_inactive_subscription_is_skipped():
    w = World()
    w.subscriptions.snapshots = [subscription(days_from=3, active=False, now=EPOCH)]
    assert w.reminders.run_expiration_reminders().queued == 0


def test_expiry_sweep_publishes_its_report():
    w = World()
    w.subscriptions.snapshots = [subscription(days_from=3, now=EPOCH)]
    w.reminders.run_expiration_reminders()
    events = w.events.of_type(ReminderJobCompleted)
    assert len(events) == 1
    assert events[0].queued == 1


def test_eighty_percent_usage_warns():
    w = World()
    w.subscriptions.snapshots = [subscription(used_gib=82.0, total_gib=100.0, now=EPOCH)]
    report = w.reminders.run_traffic_reminders()
    assert report.queued == 1
    assert _bodies(w) == ["traffic.warning"]


def test_below_the_first_threshold_is_silence():
    w = World()
    w.subscriptions.snapshots = [subscription(used_gib=50.0, total_gib=100.0, now=EPOCH)]
    assert w.reminders.run_traffic_reminders().queued == 0


def test_exhausted_traffic_uses_its_own_template():
    w = World()
    w.subscriptions.snapshots = [subscription(used_gib=100.0, total_gib=100.0, now=EPOCH)]
    w.reminders.run_traffic_reminders()
    assert _bodies(w) == ["traffic.exhausted"]


def test_unmetered_plans_are_never_warned():
    """Dividing by a null quota is how you send nonsense to Elite customers."""
    w = World()
    w.subscriptions.snapshots = [subscription(used_gib=900.0, total_gib=None, now=EPOCH)]
    report = w.reminders.run_traffic_reminders()
    assert report.queued == 0
    assert w.stored() == []


def test_traffic_dedupe_is_per_threshold():
    w = World()
    snapshot = subscription(used_gib=82.0, total_gib=100.0, now=EPOCH)
    w.subscriptions.snapshots = [snapshot]
    w.reminders.run_traffic_reminders()
    assert w.reminders.run_traffic_reminders().queued == 0

    w.subscriptions.snapshots = [subscription(used_gib=96.0, total_gib=100.0, now=EPOCH)]
    assert w.reminders.run_traffic_reminders().queued == 1
    assert _bodies(w) == ["traffic.warning", "traffic.warning"]


def test_traffic_reminders_reach_the_right_user():
    w = World()
    w.subscriptions.snapshots = [
        subscription(user_id=USER_ID + 5, used_gib=99.0, total_gib=100.0, now=EPOCH)
    ]
    w.reminders.run_traffic_reminders()
    assert w.stored()[0].user_id == USER_ID + 5
