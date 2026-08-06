"""Notification gating.

Three rules, and all three are the kind that only bite in production at 3am:
preferences are honoured, quiet hours are honoured except for critical
messages, and a blocked user is a normal outcome rather than an exception.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("aiogram", reason="notifications imports the keyboard layer")

from geekvpn.presentation.bot import notifications as N


class TestQuietHours:
    def test_late_night_is_quiet(self) -> None:
        assert N.in_quiet_hours(datetime(2026, 8, 3, 23, 30, tzinfo=UTC))

    def test_early_morning_is_quiet(self) -> None:
        assert N.in_quiet_hours(datetime(2026, 8, 3, 2, 0, tzinfo=UTC))

    def test_midday_is_not_quiet(self) -> None:
        assert not N.in_quiet_hours(datetime(2026, 8, 3, 13, 0, tzinfo=UTC))

    def test_window_wraps_midnight(self) -> None:
        """The window spans midnight, so the check must be an OR of two
        ranges. An AND silently makes every hour loud."""
        quiet = [h for h in range(24) if N.in_quiet_hours(datetime(2026, 8, 3, h, 0, tzinfo=UTC))]
        assert quiet, "no hour was quiet - the window logic collapsed"
        assert len(quiet) < 24, "every hour was quiet - the window is inverted"


class TestCategories:
    def test_critical_bypasses_quiet_hours(self) -> None:
        assert N.Category.CRITICAL.bypasses_quiet_hours

    def test_marketing_does_not_bypass(self) -> None:
        assert not N.Category.PROMOS.bypasses_quiet_hours
        assert not N.Category.NEWS.bypasses_quiet_hours

    def test_every_category_maps_to_a_preference(self) -> None:
        from geekvpn.application.bot.read_models import NotificationPreferences

        available = NotificationPreferences().as_dict()
        for category in N.Category:
            key = category.preference_key
            assert key is None or key in available
