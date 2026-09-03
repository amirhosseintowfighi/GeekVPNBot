"""Collaboration ports for the notification engine.

Synchronous, like the payment and support ports, and for the same reason: the
engine is decision logic (may we send? have we already? is it quiet?) rather
than I/O. The async boundary lives in the adapters -- the aiogram channel is
free to be async behind ``Channel``.

The channel abstraction is the important one. ``Telegram`` and ``Mini App``
are not two code paths through the engine; they are two implementations of one
Protocol, which is why adding email or SMS later is a new adapter and not a
new branch.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from geekvpn.domain.notifications.broadcast import Broadcast
from geekvpn.domain.notifications.enums import (
    AudienceKind,
    BroadcastState,
    NotificationChannel,
    SuppressionReason,
)
from geekvpn.domain.notifications.message import RenderedMessage
from geekvpn.domain.notifications.notification import Notification
from geekvpn.domain.notifications.preferences import NotificationPreferences


@runtime_checkable
class Clock(Protocol):
    """Time as a dependency. Always timezone-aware UTC."""

    def now(self) -> datetime: ...


@runtime_checkable
class IdGenerator(Protocol):
    def new_id(self) -> str: ...


@runtime_checkable
class EventPublisher(Protocol):
    def publish_all(self, events: Sequence[object]) -> None: ...


@dataclass(frozen=True, slots=True)
class ChannelResult:
    """What one channel did with one message.

    A channel reports refusal (``suppressed``) separately from breakage
    (``ok=False`` with an error). Only the second is worth retrying, and
    conflating them is how systems end up hammering a user who blocked the
    bot.
    """

    ok: bool
    suppressed: SuppressionReason | None = None
    error: str = ""

    @classmethod
    def sent(cls) -> ChannelResult:
        return cls(ok=True)

    @classmethod
    def refused(cls, reason: SuppressionReason) -> ChannelResult:
        return cls(ok=False, suppressed=reason)

    @classmethod
    def broke(cls, error: str) -> ChannelResult:
        return cls(ok=False, error=error)


@runtime_checkable
class Channel(Protocol):
    """One delivery surface.

    ``deliver`` must not raise for ordinary conditions such as a blocked bot;
    it returns a result instead. The engine still wraps calls defensively,
    because a third-party client library will eventually raise something
    nobody predicted.
    """

    @property
    def channel(self) -> NotificationChannel: ...

    def deliver(
        self,
        *,
        user_id: int,
        message: RenderedMessage,
        notification_id: str,
    ) -> ChannelResult: ...


@runtime_checkable
class PreferencesStore(Protocol):
    """Per-user switches.

    ``load`` must return defaults rather than raising for an unknown user: a
    customer who never opened settings still gets their expiry warning.
    """

    def load(self, user_id: int) -> NotificationPreferences: ...

    def save(self, user_id: int, preferences: NotificationPreferences) -> None: ...


@runtime_checkable
class NotificationRepository(Protocol):
    def get(self, notification_id: str) -> Notification: ...

    """Raises NotificationNotFound."""

    def save(self, notification: Notification) -> None: ...

    def for_user(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        limit: int = 10,
        offset: int = 0,
    ) -> list[Notification]: ...

    def count_unread(self, user_id: int) -> int: ...

    def dedupe_exists(self, user_id: int, dedupe_key: str) -> bool: ...

    """True when this exact reminder was already queued for this user."""

    def due_deferred(self, now: datetime, *, limit: int = 100) -> list[Notification]: ...

    """Notifications held for quiet hours whose window has now passed."""

    def marketing_count_since(self, user_id: int, since: datetime) -> int: ...

    """How many promotional messages this user already got in the window."""


@runtime_checkable
class BroadcastRepository(Protocol):
    def get(self, broadcast_id: str) -> Broadcast: ...

    """Raises BroadcastNotFound."""

    def save(self, broadcast: Broadcast) -> None: ...

    def due(self, now: datetime, *, limit: int = 10) -> list[Broadcast]: ...

    def listing(
        self,
        *,
        state: BroadcastState | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[Broadcast]: ...


@runtime_checkable
class AudienceResolver(Protocol):
    """Turns an audience description into Telegram user ids.

    Returns a list rather than a generator so the broadcast can record an
    honest recipient count before the first send.
    """

    def resolve(
        self,
        audience: AudienceKind,
        *,
        reference: str | None = None,
    ) -> list[int]: ...


@dataclass(frozen=True, slots=True)
class SubscriptionSnapshot:
    """The minimum a reminder sweep needs to decide whether to warn.

    ``total_gib = None`` means an unmetered plan, for which traffic reminders
    are meaningless and must be skipped rather than divided by zero.
    """

    subscription_id: str
    user_id: int
    plan_name: str
    expires_at: datetime
    used_gib: float = 0.0
    total_gib: float | None = None
    active: bool = True
    #: When traffic last moved. A weak signal: counters only grow when bytes
    #: flow, so this says nothing about somebody who connected and reached
    #: nothing - which is the customer worth asking about.
    last_used_at: datetime | None = None
    #: When the panel last saw them connected. The real answer, and what the
    #: silence is measured from.
    last_connected_at: datetime | None = None
    started_at: datetime | None = None

    def days_left(self, now: datetime) -> int:
        """Whole days remaining, rounded up, floored at zero.

        Rounded up so that anything still running today reads as at least one
        day rather than zero, which would be indistinguishable from expired.
        """
        delta = self.expires_at - now
        seconds = delta.total_seconds()
        if seconds <= 0:
            return 0
        return int((seconds + 86399) // 86400)

    def percent_used(self) -> float | None:
        if self.total_gib is None or self.total_gib <= 0:
            return None
        return min(100.0, self.used_gib * 100.0 / self.total_gib)

    def remaining_gib(self) -> float | None:
        if self.total_gib is None:
            return None
        return max(0.0, self.total_gib - self.used_gib)


@runtime_checkable
class SubscriptionReader(Protocol):
    """Read side for the reminder jobs.

    Deliberately not the subscription repository: reminders need a wide, cheap
    scan of many users, not a consistency boundary around one aggregate.
    """

    def expiring_within(self, days: int, *, now: datetime) -> list[SubscriptionSnapshot]: ...

    def with_traffic_usage(
        self, *, min_percent: float, now: datetime
    ) -> list[SubscriptionSnapshot]: ...

    def idle_since(self, hours: int, *, now: datetime) -> list[SubscriptionSnapshot]:
        """Live subscriptions the panel has not seen connect for `hours`.

        Only accounts with something left to use: somebody whose plan has
        expired or whose quota is gone is not stuck, they are finished, and
        asking them what went wrong would be the wrong conversation."""
        ...


@dataclass(frozen=True, slots=True)
class CampaignSnapshot:
    """A marketing campaign worth announcing."""

    campaign_id: str
    title_fa: str
    discount_percent: int
    starts_at: datetime
    ends_at: datetime
    audience: AudienceKind = AudienceKind.ALL
    audience_ref: str | None = None
    announced: bool = False

    def is_live(self, now: datetime) -> bool:
        return self.starts_at <= now <= self.ends_at


@runtime_checkable
class CampaignReader(Protocol):
    def unannounced(self, *, now: datetime) -> list[CampaignSnapshot]: ...

    def mark_announced(self, campaign_id: str, *, now: datetime) -> None: ...


@dataclass(slots=True)
class NotificationServices:
    """Everything the presentation layer needs, assembled once at startup."""

    engine: object
    reminders: object
    broadcasts: object
    campaigns: object
    inbox: object
    scheduler: object
    extras: dict[str, object] = field(default_factory=dict)


__all__ = [
    "AudienceResolver",
    "BroadcastRepository",
    "CampaignReader",
    "CampaignSnapshot",
    "Channel",
    "ChannelResult",
    "Clock",
    "EventPublisher",
    "IdGenerator",
    "NotificationRepository",
    "NotificationServices",
    "PreferencesStore",
    "SubscriptionReader",
    "SubscriptionSnapshot",
]
