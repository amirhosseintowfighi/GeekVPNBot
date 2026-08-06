"""Quiet hours and preference toggles."""

from __future__ import annotations

from datetime import UTC, datetime

from geekvpn.domain.notifications.enums import (
    NotificationCategory,
    NotificationChannel,
)
from geekvpn.domain.notifications.preferences import (
    ChannelPreferences,
    NotificationPreferences,
    QuietHours,
    local_hour,
)


def _utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 3, hour, minute, tzinfo=UTC)


def test_local_hour_applies_iran_half_hour_offset():
    assert local_hour(_utc(10, 0)) == 13
    assert local_hour(_utc(10, 45)) == 14


def test_local_hour_treats_naive_datetime_as_utc():
    naive = datetime(2026, 8, 3, 10, 0)
    assert local_hour(naive) == local_hour(_utc(10, 0))


def test_quiet_window_wraps_midnight():
    """The classic bug: an AND here would make the window empty."""
    quiet = QuietHours()
    assert quiet.covers_hour(23)
    assert quiet.covers_hour(2)
    assert quiet.covers_hour(7)
    assert not quiet.covers_hour(8)
    assert not quiet.covers_hour(13)
    assert not quiet.covers_hour(22)


def test_disabled_quiet_hours_cover_nothing():
    quiet = QuietHours(enabled=False)
    assert not quiet.covers_hour(2)


def test_next_open_time_returns_now_when_not_quiet():
    quiet = QuietHours()
    moment = _utc(10)
    assert quiet.next_open_time(moment) == moment


def test_next_open_time_lands_at_end_of_window():
    """04:00 Iran should flush at 08:00 Iran, which is 04:30 UTC."""
    quiet = QuietHours()
    inside = _utc(0, 30)
    reopened = quiet.next_open_time(inside)
    assert reopened > inside
    assert local_hour(reopened) == 8


def test_every_category_is_on_by_default():
    """Opt-out, not opt-in: a broadcast nobody receives is a broken feature."""
    prefs = NotificationPreferences()
    assert prefs.expiry is True
    assert prefs.traffic is True
    assert prefs.promos is True
    assert prefs.news is True


def test_critical_is_allowed_even_when_everything_is_muted():
    prefs = NotificationPreferences(expiry=False, traffic=False, promos=False, news=False)
    assert prefs.allows_category(NotificationCategory.CRITICAL)
    assert not prefs.allows_category(NotificationCategory.EXPIRY)


def test_toggling_returns_a_new_instance():
    prefs = NotificationPreferences()
    toggled = prefs.with_toggled("promos")
    assert toggled is not prefs
    assert prefs.promos is True
    assert toggled.promos is False


def test_unknown_toggle_key_returns_self_by_identity():
    prefs = NotificationPreferences()
    assert prefs.with_toggled("nonsense") is prefs


def test_quiet_hours_toggle_reaches_the_nested_object():
    prefs = NotificationPreferences()
    toggled = prefs.with_toggled("quiet_hours")
    assert toggled.quiet.enabled is False
    assert prefs.quiet.enabled is True


def test_channel_toggle_reaches_the_nested_object():
    prefs = NotificationPreferences()
    toggled = prefs.with_toggled("telegram")
    assert toggled.allows_channel(NotificationChannel.TELEGRAM) is False
    assert toggled.allows_channel(NotificationChannel.MINIAPP) is True


def test_as_dict_exposes_every_switch():
    keys = set(NotificationPreferences().as_dict())
    assert keys == {
        "expiry",
        "traffic",
        "promos",
        "news",
        "quiet_hours",
        "telegram",
        "miniapp",
    }


def test_channel_preferences_allow_both_by_default():
    channels = ChannelPreferences()
    assert channels.allows(NotificationChannel.TELEGRAM)
    assert channels.allows(NotificationChannel.MINIAPP)
