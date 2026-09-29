"""When the wallet renews a service by itself."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from geekvpn.application.provisioning.auto_renew import RenewalCandidate, is_due

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _candidate(**changes: object) -> RenewalCandidate:
    values: dict[str, object] = {
        "subscription_id": "s1",
        "telegram_id": 42,
        "plan_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
        "expires_at": NOW + timedelta(days=10),
        "traffic_limit_mib": 50 * 1024,
        "traffic_used_mib": 10 * 1024,
        "last_attempt_at": None,
    }
    values.update(changes)
    return RenewalCandidate(**values)  # type: ignore[arg-type]


def test_a_healthy_service_is_left_alone():
    assert not is_due(_candidate(), NOW)


def test_a_day_before_expiry_it_renews():
    assert is_due(_candidate(expires_at=NOW + timedelta(hours=23)), NOW)


def test_nearly_out_of_traffic_it_renews():
    assert is_due(_candidate(traffic_used_mib=50 * 1024 - 90), NOW)
    # 3% of a large quota counts as nearly out too.
    assert is_due(_candidate(traffic_limit_mib=500 * 1024, traffic_used_mib=490 * 1024), NOW)


def test_unlimited_traffic_waits_for_the_date():
    assert not is_due(_candidate(traffic_limit_mib=None, traffic_used_mib=10**9), NOW)


def test_a_failed_attempt_waits_before_trying_again():
    soon = NOW + timedelta(hours=2)
    assert not is_due(_candidate(expires_at=soon, last_attempt_at=NOW - timedelta(hours=1)), NOW)
    assert is_due(_candidate(expires_at=soon, last_attempt_at=NOW - timedelta(hours=13)), NOW)


def test_a_service_without_a_plan_never_renews():
    assert not is_due(_candidate(plan_id=None, expires_at=NOW + timedelta(hours=1)), NOW)
