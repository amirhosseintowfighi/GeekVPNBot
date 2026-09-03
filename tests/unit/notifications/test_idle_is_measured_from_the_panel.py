"""The silence is measured from when the panel last saw them, not from traffic.

The first version keyed on `last_used_at`, which moves only when the byte
counter grows. Two things were wrong with that.

It answers a different question. A customer who connects and reaches nothing
moves no bytes, and they are precisely the customer this message exists for.

And it had never been written at all, because the usage sweep was broken - so
the clock fell back to the purchase date, and the message went to people who
were connecting every day. That is what "much sooner than 72 hours" looked like
from the outside.

Panels report `online_at`. That is the answer, and now it is what is stored.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.domain.provisioning.subscription import Subscription

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)


def _subscription(**kwargs) -> Subscription:
    base = {
        "user_id": 1,
        "order_id": "o1",
        "plan_id": "p1",
        "started_at": NOW - timedelta(days=30),
        "expires_at": NOW + timedelta(days=30),
        "remote_username": "ali",
        "traffic_limit_mib": 50_000,
    }
    base.update(kwargs)
    return Subscription("s1", **base)


def test_the_panels_last_seen_is_recorded():
    subscription = _subscription()

    subscription.record_usage(used_mib=10, at=NOW, online_at=NOW - timedelta(hours=1))

    assert subscription.last_connected_at == NOW - timedelta(hours=1)


def test_it_only_moves_forward():
    """Panels round this value and nodes report late. A reading that went
    backwards would reset the silence we are measuring."""
    subscription = _subscription()
    subscription.record_usage(used_mib=10, at=NOW, online_at=NOW - timedelta(hours=1))

    subscription.record_usage(used_mib=20, at=NOW, online_at=NOW - timedelta(days=5))

    assert subscription.last_connected_at == NOW - timedelta(hours=1)


def test_a_panel_that_does_not_report_it_leaves_it_alone():
    """The x-ui family does not. Writing `now` here would mark every customer
    as having just connected, and nobody would ever be asked anything."""
    subscription = _subscription()

    subscription.record_usage(used_mib=10, at=NOW, online_at=None)

    assert subscription.last_connected_at is None


def test_it_is_not_the_same_thing_as_traffic_moving():
    """The distinction the whole fix rests on. Bytes flowed a moment ago and
    the panel last saw them three days back - a session that connected and
    then sat there is still a session."""
    subscription = _subscription()

    subscription.record_usage(used_mib=500, at=NOW, online_at=NOW - timedelta(days=3))

    assert subscription.last_used_at == NOW
    assert subscription.last_connected_at == NOW - timedelta(days=3)


def test_usage_still_only_moves_forward_too():
    subscription = _subscription()
    subscription.record_usage(used_mib=500, at=NOW)

    subscription.record_usage(used_mib=10, at=NOW + timedelta(minutes=10))

    assert subscription.traffic_used_mib == 500
