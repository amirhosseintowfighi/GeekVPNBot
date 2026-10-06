"""When the wallet renews a service by itself.

The app's rule and the bot's, joined: a day before the date, or when the
traffic is nearly gone - whichever comes first.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from geekvpn.application.provisioning.auto_renew import needs_renewal, traffic_nearly_out

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _due(**changes: object) -> bool:
    values: dict[str, object] = {
        "expires_at": NOW + timedelta(days=10),
        "traffic_limit_mib": 50 * 1024,
        "traffic_used_mib": 10 * 1024,
        "now": NOW,
    }
    values.update(changes)
    return needs_renewal(**values)  # type: ignore[arg-type]


def test_a_healthy_service_is_left_alone():
    assert not _due()


def test_a_day_before_expiry_it_renews():
    assert _due(expires_at=NOW + timedelta(hours=23))


def test_nearly_out_of_traffic_it_renews():
    assert _due(traffic_used_mib=50 * 1024 - 90)
    # 3% of a large quota counts as nearly out too.
    assert _due(traffic_limit_mib=500 * 1024, traffic_used_mib=490 * 1024)


def test_unlimited_traffic_waits_for_the_date():
    assert not _due(traffic_limit_mib=None, traffic_used_mib=10**9)
    assert not traffic_nearly_out(0, 10**9)
