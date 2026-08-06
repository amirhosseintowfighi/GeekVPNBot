"""The notification engine.

One entry point, ``notify``, used by every producer in the system: reminder
sweeps, payment event handlers, the support system, broadcasts and campaigns.
Centralising it means the four rules below are enforced once instead of being
re-implemented, slightly differently, at every call site.

1. **Preferences win.** A muted category is never sent, whatever the caller
   asks for. Only CRITICAL bypasses this, because "your money moved" and
   "your service is dead" are not marketing.

2. **Quiet hours defer, they do not discard.** A traffic warning generated at
   3am is held and flushed at 08:00 Iran time. Discarding it would mean the
   customer never learns; sending it would mean a phone buzzing at 3am.

3. **The Mini App inbox ignores quiet hours.** It is a pull surface: writing a
   row wakes nobody. This is why the inbox is always in the channel set --
   even a customer who blocked the bot can still find out what happened.

4. **Channels are isolated.** Telegram raising must not stop the inbox write,
   and neither failure may propagate into the scheduler that called us. A
   sweep over 5,000 users cannot die on user 12.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from geekvpn.application.notifications.ports import (
    Channel,
    ChannelResult,
    Clock,
    EventPublisher,
    IdGenerator,
    NotificationRepository,
    PreferencesStore,
)
from geekvpn.domain.notifications.enums import (
    DeliveryState,
    NotificationChannel,
    SuppressionReason,
)
from geekvpn.domain.notifications.message import RenderedMessage, render
from geekvpn.domain.notifications.notification import Notification
from geekvpn.domain.notifications.preferences import (
    DEFAULT_PREFERENCES,
    NotificationPreferences,
)

# A customer may receive at most this many marketing messages per rolling day.
# Transactional categories are never counted or limited.
MARKETING_DAILY_CAP = 2

DEFAULT_CHANNELS: tuple[NotificationChannel, ...] = (
    NotificationChannel.TELEGRAM,
    NotificationChannel.MINIAPP,
)


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """Outcome of one ``notify`` call across all of its channels."""

    notification_id: str | None
    user_id: int
    outcomes: Mapping[NotificationChannel, DeliveryState]
    skipped: SuppressionReason | None = None

    @property
    def delivered(self) -> bool:
        return any(state.is_success() for state in self.outcomes.values())

    @property
    def deferred(self) -> bool:
        return any(state is DeliveryState.DEFERRED for state in self.outcomes.values())

    @property
    def was_queued(self) -> bool:
        """False when the engine refused before creating anything at all."""
        return self.notification_id is not None


class NotificationEngine:
    """Renders Persian copy, decides, delivers, and records."""

    def __init__(
        self,
        *,
        notifications: NotificationRepository,
        preferences: PreferencesStore,
        channels: Sequence[Channel],
        clock: Clock,
        ids: IdGenerator,
        events: EventPublisher,
        marketing_daily_cap: int = MARKETING_DAILY_CAP,
    ) -> None:
        self._notifications = notifications
        self._preferences = preferences
        self._channels: dict[NotificationChannel, Channel] = {
            channel.channel: channel for channel in channels
        }
        self._clock = clock
        self._ids = ids
        self._events = events
        self._marketing_daily_cap = marketing_daily_cap

    # ---- Public API -----------------------------------------------------

    def notify(
        self,
        *,
        user_id: int,
        template_key: str,
        fields: Mapping[str, Any] | None = None,
        channels: Sequence[NotificationChannel] | None = None,
        dedupe_key: str | None = None,
        source: str | None = None,
        force: bool = False,
    ) -> DispatchResult:
        """Render, decide and deliver.

        ``force`` bypasses preferences and quiet hours. It exists for one
        legitimate case -- an operator manually resending something the
        customer asked for -- and is never set by a scheduled job.
        """
        now = self._clock.now()
        message = render(template_key, **dict(fields or {}))
        return self.dispatch(
            user_id=user_id,
            message=message,
            channels=channels,
            dedupe_key=dedupe_key,
            source=source,
            force=force,
            now=now,
        )

    def dispatch(
        self,
        *,
        user_id: int,
        message: RenderedMessage,
        channels: Sequence[NotificationChannel] | None = None,
        dedupe_key: str | None = None,
        source: str | None = None,
        force: bool = False,
        now: datetime | None = None,
    ) -> DispatchResult:
        """Deliver an already-rendered message. Used by broadcast fan-out."""
        now = now or self._clock.now()
        targets = tuple(channels) if channels else DEFAULT_CHANNELS

        if dedupe_key and self._notifications.dedupe_exists(user_id, dedupe_key):
            return DispatchResult(
                notification_id=None,
                user_id=user_id,
                outcomes={},
                skipped=SuppressionReason.DUPLICATE,
            )

        preferences = self._load_preferences(user_id)

        if not force and not preferences.allows_category(message.category):
            return DispatchResult(
                notification_id=None,
                user_id=user_id,
                outcomes={},
                skipped=SuppressionReason.MUTED,
            )

        if not force and self._marketing_capped(user_id, message, now):
            return DispatchResult(
                notification_id=None,
                user_id=user_id,
                outcomes={},
                skipped=SuppressionReason.RATE_LIMITED,
            )

        notification = Notification.queue(
            self._ids.new_id(),
            user_id=user_id,
            message=message,
            channels=targets,
            now=now,
            dedupe_key=dedupe_key,
            source=source,
        )

        for channel in targets:
            self._attempt(
                notification,
                channel=channel,
                preferences=preferences,
                now=now,
                force=force,
            )

        self._notifications.save(notification)
        self._events.publish_all(notification.collect_events())

        return DispatchResult(
            notification_id=notification.id,
            user_id=user_id,
            outcomes={
                channel: notification.state_for(channel) or DeliveryState.PENDING
                for channel in targets
            },
        )

    def flush_deferred(self, *, limit: int = 100) -> list[DispatchResult]:
        """Send everything whose quiet window has passed.

        Run by the DEFERRED_FLUSH job. Preferences are re-read rather than
        trusted from queue time: a customer who muted traffic warnings at
        midnight should not receive one at dawn.
        """
        now = self._clock.now()
        results: list[DispatchResult] = []

        for notification in self._notifications.due_deferred(now, limit=limit):
            preferences = self._load_preferences(notification.user_id)
            due = notification.due_channels(now)
            if not due:
                continue

            if not preferences.allows_category(notification.category):
                for channel in due:
                    notification.mark_suppressed(channel, reason=SuppressionReason.MUTED, now=now)
            else:
                for channel in due:
                    self._attempt(
                        notification,
                        channel=channel,
                        preferences=preferences,
                        now=now,
                        force=True,
                    )

            self._notifications.save(notification)
            self._events.publish_all(notification.collect_events())
            results.append(
                DispatchResult(
                    notification_id=notification.id,
                    user_id=notification.user_id,
                    outcomes={
                        channel: notification.state_for(channel) or DeliveryState.PENDING
                        for channel in due
                    },
                )
            )

        return results

    # ---- Internals ------------------------------------------------------

    def _load_preferences(self, user_id: int) -> NotificationPreferences:
        """A broken preference store must not silence the whole system.

        Falling back to defaults means the worst case is a customer receiving
        something they muted, which is far better than an outage in which
        nobody learns their service expired.
        """
        try:
            return self._preferences.load(user_id)
        except Exception:
            return DEFAULT_PREFERENCES

    def _marketing_capped(self, user_id: int, message: RenderedMessage, now: datetime) -> bool:
        if not message.category.is_marketing:
            return False
        try:
            recent = self._notifications.marketing_count_since(user_id, now - timedelta(days=1))
        except Exception:
            return False
        return recent >= self._marketing_daily_cap

    def _attempt(
        self,
        notification: Notification,
        *,
        channel: NotificationChannel,
        preferences: NotificationPreferences,
        now: datetime,
        force: bool,
    ) -> None:
        adapter = self._channels.get(channel)
        if adapter is None:
            notification.mark_suppressed(
                channel, reason=SuppressionReason.CHANNEL_DISABLED, now=now
            )
            return

        if not force and not preferences.allows_channel(channel):
            notification.mark_suppressed(
                channel, reason=SuppressionReason.CHANNEL_DISABLED, now=now
            )
            return

        if self._should_defer(channel, notification, preferences, now, force):
            notification.defer(
                channel,
                send_after=preferences.quiet.next_open_time(now),
                now=now,
            )
            return

        try:
            result = adapter.deliver(
                user_id=notification.user_id,
                message=notification.message,
                notification_id=notification.id,
            )
        except Exception as exc:
            notification.mark_failed(channel, error=type(exc).__name__, now=now)
            return

        self._record(notification, channel=channel, result=result, now=now)

    def _should_defer(
        self,
        channel: NotificationChannel,
        notification: Notification,
        preferences: NotificationPreferences,
        now: datetime,
        force: bool,
    ) -> bool:
        if force:
            return False
        if channel is NotificationChannel.MINIAPP:
            # A pull surface wakes nobody, so quiet hours do not apply.
            return False
        if notification.category.bypasses_quiet_hours:
            return False
        return preferences.is_quiet_at(now)

    @staticmethod
    def _record(
        notification: Notification,
        *,
        channel: NotificationChannel,
        result: ChannelResult,
        now: datetime,
    ) -> None:
        if result.ok:
            notification.mark_sent(channel, now=now)
        elif result.suppressed is not None:
            notification.mark_suppressed(channel, reason=result.suppressed, now=now)
        else:
            notification.mark_failed(channel, error=result.error or "unknown_error", now=now)


__all__ = [
    "DEFAULT_CHANNELS",
    "MARKETING_DAILY_CAP",
    "DispatchResult",
    "NotificationEngine",
]
