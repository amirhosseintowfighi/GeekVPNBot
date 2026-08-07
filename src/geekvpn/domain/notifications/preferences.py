"""User notification preferences and the quiet-hours policy.

This is the domain-level twin of ``application.bot.read_models``'s
``NotificationPreferences``. The read model is a flat DTO the settings screen
renders; this one carries the *policy* -- it can answer "may I send this
category on this channel at this instant?" without the caller reimplementing
the rules.

Defaults intentionally match the existing bot read model, including
``news = True``: announcements are opt-out. A broadcast nobody receives
is a broken feature, so the switch defaults on and the customer turns it off.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from geekvpn.domain.notifications.enums import (
    NotificationCategory,
    NotificationChannel,
)

QUIET_START = 23
QUIET_END = 8

# Iran is UTC+03:30 and has not observed DST since 2022, so a fixed offset is
# correct and keeps the domain free of a tzdata dependency.
IRAN_UTC_OFFSET_HOURS = 3.5


def local_hour(now: datetime, *, offset_hours: float = IRAN_UTC_OFFSET_HOURS) -> int:
    """Hour of day in Iran time. Naive datetimes are assumed to be UTC."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    shifted = now.timestamp() + offset_hours * 3600
    return int((shifted // 3600) % 24)


@dataclass(frozen=True, slots=True)
class QuietHours:
    """The window during which non-critical notifications are held.

    The window wraps midnight, so membership is an OR of the two half-open
    ranges, never an AND. Getting this backwards is the classic bug: an AND
    would make the window empty and every 3am traffic warning would go out.
    """

    start_hour: int = QUIET_START
    end_hour: int = QUIET_END
    enabled: bool = True

    def covers_hour(self, hour: int) -> bool:
        if not self.enabled:
            return False
        if self.start_hour == self.end_hour:
            return False
        if self.start_hour < self.end_hour:
            return self.start_hour <= hour < self.end_hour
        return hour >= self.start_hour or hour < self.end_hour

    def covers(self, now: datetime) -> bool:
        return self.covers_hour(local_hour(now))

    def next_open_time(self, now: datetime) -> datetime:
        """The first instant after ``now`` at which sending is allowed again.

        Returns ``now`` unchanged when the window does not apply, so callers
        can use the result unconditionally as a send-at timestamp.
        """
        if not self.covers(now):
            return now
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        candidate = now
        # At most 24 hourly steps are ever needed to leave the window.
        for _ in range(24):
            candidate = candidate + timedelta(hours=1)
            candidate = candidate.replace(minute=0, second=0, microsecond=0)
            if not self.covers(candidate):
                return candidate
        return now


@dataclass(frozen=True, slots=True)
class ChannelPreferences:
    """Per-channel opt-out.

    The Mini App inbox defaults on and realistically stays on: it is a pull
    surface, so it costs the customer nothing. Telegram is the one people
    actually want to silence.
    """

    telegram: bool = True
    miniapp: bool = True

    def allows(self, channel: NotificationChannel) -> bool:
        if channel is NotificationChannel.TELEGRAM:
            return self.telegram
        return self.miniapp


@dataclass(frozen=True, slots=True)
class NotificationPreferences:
    """Everything the engine needs to decide whether to send.

    Immutable; ``with_toggled`` returns a new instance and returns ``self``
    *by identity* for an unknown key, which is how the settings handler spots
    a stale button from an older deploy.
    """

    expiry: bool = True
    traffic: bool = True
    promos: bool = True
    news: bool = True
    quiet: QuietHours = QuietHours()
    channels: ChannelPreferences = ChannelPreferences()

    def allows_category(self, category: NotificationCategory) -> bool:
        key = category.preference_key
        if key is None:
            return True
        return bool(self.as_dict().get(key, True))

    def allows_channel(self, channel: NotificationChannel) -> bool:
        return self.channels.allows(channel)

    def is_quiet_at(self, now: datetime) -> bool:
        return self.quiet.covers(now)

    def as_dict(self) -> dict[str, bool]:
        return {
            "expiry": self.expiry,
            "traffic": self.traffic,
            "promos": self.promos,
            "news": self.news,
            "quiet_hours": self.quiet.enabled,
            "telegram": self.channels.telegram,
            "miniapp": self.channels.miniapp,
        }

    def with_toggled(self, key: str) -> NotificationPreferences:
        if key in ("expiry", "traffic", "promos", "news"):
            # The key set is checked on the line above, which is more than a
            # checker can do with a name built at runtime.
            return replace(self, **{key: not getattr(self, key)})  # type: ignore[arg-type]
        if key == "quiet_hours":
            return replace(self, quiet=replace(self.quiet, enabled=not self.quiet.enabled))
        if key in ("telegram", "miniapp"):
            return replace(
                self,
                channels=replace(self.channels, **{key: not getattr(self.channels, key)}),
            )
        return self


DEFAULT_PREFERENCES = NotificationPreferences()


__all__ = [
    "DEFAULT_PREFERENCES",
    "IRAN_UTC_OFFSET_HOURS",
    "QUIET_END",
    "QUIET_START",
    "ChannelPreferences",
    "NotificationPreferences",
    "QuietHours",
    "local_hour",
]
