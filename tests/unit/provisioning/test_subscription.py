"""Subscription behaviour, especially the arithmetic customers complain about."""

from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.domain.provisioning import (
    Subscription,
    SubscriptionRevoked,
    SubscriptionState,
)

NOW = datetime(2026, 8, 3, 20, 0, tzinfo=UTC)
GIB = 1024


def make_sub(**kwargs):
    defaults = {
        "user_id": 1001,
        "order_id": "ord-1",
        "plan_id": "plan-90",
        "remote_username": "gv_1001_a1b2",
        "now": NOW,
        "duration_days": 30,
        "traffic_limit_mib": 100 * GIB,
    }
    defaults.update(kwargs)
    return Subscription.activate("sub-1", **defaults)


def test_activation_sets_the_term_and_announces_it():
    sub = make_sub()
    assert sub.state is SubscriptionState.ACTIVE
    assert sub.expires_at == NOW + timedelta(days=30)
    assert sub.remaining_days(NOW) == 30
    assert [e.name for e in sub.collect_events()] == ["provisioning.subscription.activated.v1"]


def test_usage_is_replaced_not_accumulated():
    sub = make_sub()
    sub.record_usage(used_mib=10 * GIB, at=NOW)
    # The same sync arriving twice must not double-count.
    sub.record_usage(used_mib=10 * GIB, at=NOW)
    assert sub.traffic_used_mib == 10 * GIB
    assert sub.usage_percent() == 10.0


def test_a_panel_that_forgot_its_counters_cannot_hand_traffic_back():
    sub = make_sub()
    sub.record_usage(used_mib=40 * GIB, at=NOW)
    sub.record_usage(used_mib=0, at=NOW + timedelta(hours=1))
    assert sub.traffic_used_mib == 40 * GIB


def test_crossing_the_quota_exhausts_the_subscription():
    sub = make_sub()
    sub.collect_events()
    sub.record_usage(used_mib=100 * GIB, at=NOW)
    assert sub.state is SubscriptionState.EXHAUSTED
    assert sub.is_usable_at(NOW) is False
    assert [e.name for e in sub.collect_events()] == ["provisioning.subscription.exhausted.v1"]


def test_adding_traffic_revives_an_exhausted_subscription():
    sub = make_sub()
    sub.record_usage(used_mib=100 * GIB, at=NOW)
    sub.add_traffic(extra_mib=20 * GIB)
    assert sub.state is SubscriptionState.ACTIVE
    assert sub.remaining_mib == 20 * GIB


def test_renewing_early_does_not_burn_the_days_already_paid_for():
    sub = make_sub()
    early = NOW + timedelta(days=10)
    sub.renew(days=30, now=early)
    # 20 days were left, so the new expiry is 20 + 30 days away, not 30.
    assert sub.expires_at == NOW + timedelta(days=60)


def test_renewing_after_expiry_starts_from_today():
    sub = make_sub()
    late = NOW + timedelta(days=45)
    sub.expire(now=late)
    sub.renew(days=30, now=late)
    assert sub.expires_at == late + timedelta(days=30)
    assert sub.state is SubscriptionState.ACTIVE


def test_expiry_reminders_do_not_arrive_as_a_burst_after_an_outage():
    sub = make_sub()
    # The job was down; we are now one day from expiry, having sent nothing.
    one_day_left = sub.expires_at - timedelta(days=1)
    due = sub.due_expiry_reminder(now=one_day_left)
    assert due == 1
    sub.mark_expiry_notified(1)
    assert sub.due_expiry_reminder(now=one_day_left) is None
    # The superseded steps must stay silent too.
    assert sub.notified_expiry_days == frozenset({7, 3, 1})


def test_traffic_reminders_report_the_highest_threshold_crossed():
    sub = make_sub()
    sub.record_usage(used_mib=96 * GIB, at=NOW)
    # Past both 80 and 95: say the urgent thing, not the stale one.
    assert sub.due_traffic_reminder() == 95
    sub.mark_traffic_notified(95)
    # ...and 80 must not follow it afterwards.
    assert sub.due_traffic_reminder() is None


def test_traffic_reminder_fires_once_per_threshold():
    sub = make_sub()
    sub.record_usage(used_mib=85 * GIB, at=NOW)
    assert sub.due_traffic_reminder() == 80
    sub.mark_traffic_notified(80)
    assert sub.due_traffic_reminder() is None
    sub.record_usage(used_mib=96 * GIB, at=NOW)
    assert sub.due_traffic_reminder() == 95


def test_unlimited_plans_never_exhaust_and_never_nag():
    sub = make_sub(traffic_limit_mib=None)
    sub.record_usage(used_mib=900 * GIB, at=NOW)
    assert sub.is_exhausted() is False
    assert sub.usage_percent() == 0.0
    assert sub.due_traffic_reminder() is None


def test_resuming_lands_in_whatever_state_reality_dictates():
    sub = make_sub()
    sub.suspend(reason_fa="بررسی تخلف")
    assert sub.state is SubscriptionState.SUSPENDED
    after_expiry = sub.expires_at + timedelta(days=1)
    sub.resume(now=after_expiry)
    assert sub.state is SubscriptionState.EXPIRED


def test_revocation_is_terminal():
    sub = make_sub()
    sub.revoke(reason_fa="سوءاستفاده", at=NOW)
    assert sub.state is SubscriptionState.REVOKED
    with pytest.raises(SubscriptionRevoked):
        sub.renew(days=30, now=NOW)


def test_restore_rebuilds_without_emitting_anything():
    sub = Subscription.restore(
        "sub-9",
        user_id=1001,
        order_id="ord-1",
        plan_id="plan-30",
        remote_username="gv_1001_zz",
        started_at=NOW,
        expires_at=NOW + timedelta(days=30),
        state=SubscriptionState.EXHAUSTED,
        traffic_limit_mib=50 * GIB,
        traffic_used_mib=50 * GIB,
        notified_traffic_percents=[80, 95],
    )
    assert sub.state is SubscriptionState.EXHAUSTED
    assert sub.notified_traffic_percents == frozenset({80, 95})
    assert sub.collect_events() == []
