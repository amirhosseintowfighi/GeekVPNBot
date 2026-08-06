"""In-memory fakes for the notification engine.

The channels are the interesting ones. ``RecordingChannel`` can be told to
succeed, refuse or explode, which is how channel isolation gets tested: a
Telegram channel that raises must not stop the Mini App inbox write.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from geekvpn.application.notifications.ports import (
    CampaignSnapshot,
    ChannelResult,
    SubscriptionSnapshot,
)
from geekvpn.domain.notifications.broadcast import Broadcast
from geekvpn.domain.notifications.enums import (
    AudienceKind,
    BroadcastState,
    DeliveryState,
    NotificationChannel,
)
from geekvpn.domain.notifications.errors import BroadcastNotFound, NotificationNotFound
from geekvpn.domain.notifications.notification import Notification
from geekvpn.domain.notifications.preferences import (
    DEFAULT_PREFERENCES,
    NotificationPreferences,
)

# 10:00 UTC is 13:30 in Iran: comfortably outside quiet hours, so tests that
# do not care about timing are never accidentally deferred.
EPOCH = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)

# 21:00 UTC is 00:30 in Iran: inside the quiet window.
QUIET_EPOCH = datetime(2026, 8, 3, 21, 0, tzinfo=UTC)

USER_ID = 1001
ADMIN_ID = 9001


class FakeClock:
    def __init__(self, now: datetime = EPOCH) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, *, minutes: int = 0, hours: int = 0, days: int = 0) -> None:
        self._now = self._now + timedelta(minutes=minutes, hours=hours, days=days)

    def set(self, moment: datetime) -> None:
        self._now = moment


class FakeIds:
    def __init__(self) -> None:
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"ntf-{self._counter:04d}"


class FakeEvents:
    def __init__(self) -> None:
        self.published: list[object] = []

    def publish_all(self, events: Sequence[object]) -> None:
        self.published.extend(events)

    def of_type(self, cls) -> list:
        return [e for e in self.published if isinstance(e, cls)]

    def names(self) -> list[str]:
        return [type(e).__name__ for e in self.published]


class FakePreferences:
    """Preference store. ``explode`` proves the engine survives a broken store."""

    def __init__(self) -> None:
        self._by_user: dict[int, NotificationPreferences] = {}
        self.explode = False
        self.saved: list[tuple[int, NotificationPreferences]] = []

    def load(self, user_id: int) -> NotificationPreferences:
        if self.explode:
            raise RuntimeError("preference store is down")
        return self._by_user.get(user_id, DEFAULT_PREFERENCES)

    def save(self, user_id: int, preferences: NotificationPreferences) -> None:
        self._by_user[user_id] = preferences
        self.saved.append((user_id, preferences))

    def set_for(self, user_id: int, preferences: NotificationPreferences) -> None:
        self._by_user[user_id] = preferences


class FakeNotificationRepository:
    def __init__(self) -> None:
        self.rows: dict[str, Notification] = {}
        self.save_calls = 0

    def get(self, notification_id: str) -> Notification:
        try:
            return self.rows[notification_id]
        except KeyError:
            raise NotificationNotFound(notification_id) from None

    def save(self, notification: Notification) -> None:
        self.rows[notification.id] = notification
        self.save_calls += 1

    def for_user(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        limit: int = 10,
        offset: int = 0,
    ) -> list[Notification]:
        rows = [n for n in self.rows.values() if n.user_id == user_id]
        if unread_only:
            rows = [n for n in rows if n.is_unread()]
        rows.sort(key=lambda n: n.created_at, reverse=True)
        return rows[offset : offset + limit]

    def count_unread(self, user_id: int) -> int:
        return len([n for n in self.rows.values() if n.user_id == user_id and n.is_unread()])

    def dedupe_exists(self, user_id: int, dedupe_key: str) -> bool:
        return any(n.user_id == user_id and n.dedupe_key == dedupe_key for n in self.rows.values())

    def due_deferred(self, now: datetime, *, limit: int = 100) -> list[Notification]:
        out: list[Notification] = []
        for notification in self.rows.values():
            for attempt in notification.deliveries():
                if attempt.state is DeliveryState.DEFERRED and (
                    attempt.send_after is None or attempt.send_after <= now
                ):
                    out.append(notification)
                    break
        return out[:limit]

    def marketing_count_since(self, user_id: int, since: datetime) -> int:
        return len(
            [
                n
                for n in self.rows.values()
                if n.user_id == user_id and n.category.is_marketing and n.created_at >= since
            ]
        )


class FakeBroadcastRepository:
    def __init__(self) -> None:
        self.rows: dict[str, Broadcast] = {}

    def get(self, broadcast_id: str) -> Broadcast:
        try:
            return self.rows[broadcast_id]
        except KeyError:
            raise BroadcastNotFound(broadcast_id) from None

    def save(self, broadcast: Broadcast) -> None:
        self.rows[broadcast.id] = broadcast

    def due(self, now: datetime, *, limit: int = 10) -> list[Broadcast]:
        return [b for b in self.rows.values() if b.is_due(now)][:limit]

    def listing(
        self,
        *,
        state: BroadcastState | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[Broadcast]:
        rows = list(self.rows.values())
        if state is not None:
            rows = [b for b in rows if b.state is state]
        return rows[offset : offset + limit]


class FakeAudience:
    def __init__(self, ids: list[int] | None = None) -> None:
        self.ids = ids if ids is not None else [USER_ID]
        self.calls: list[tuple[AudienceKind, str | None]] = []

    def resolve(self, audience: AudienceKind, *, reference: str | None = None) -> list[int]:
        self.calls.append((audience, reference))
        return list(self.ids)


class FakeSubscriptions:
    def __init__(self, snapshots: list[SubscriptionSnapshot] | None = None) -> None:
        self.snapshots = snapshots or []

    def expiring_within(self, days: int, *, now: datetime) -> list[SubscriptionSnapshot]:
        horizon = now + timedelta(days=days)
        return [s for s in self.snapshots if s.expires_at <= horizon]

    def with_traffic_usage(
        self, *, min_percent: float, now: datetime
    ) -> list[SubscriptionSnapshot]:
        out = []
        for snapshot in self.snapshots:
            percent = snapshot.percent_used()
            if percent is not None and percent >= min_percent:
                out.append(snapshot)
        return out


class FakeCampaigns:
    def __init__(self, campaigns: list[CampaignSnapshot] | None = None) -> None:
        self.campaigns = campaigns or []
        self.announced: list[str] = []

    def unannounced(self, *, now: datetime) -> list[CampaignSnapshot]:
        return [c for c in self.campaigns if not c.announced]

    def mark_announced(self, campaign_id: str, *, now: datetime) -> None:
        self.announced.append(campaign_id)


class RecordingChannel:
    """A channel whose behaviour a test can dictate."""

    def __init__(
        self,
        kind: NotificationChannel,
        *,
        result: ChannelResult | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._kind = kind
        self._result = result or ChannelResult.sent()
        self._raises = raises
        self.calls: list[tuple[int, str]] = []

    @property
    def channel(self) -> NotificationChannel:
        return self._kind

    def deliver(self, *, user_id, message, notification_id) -> ChannelResult:
        self.calls.append((user_id, message.key))
        if self._raises is not None:
            raise self._raises
        return self._result

    def set_result(self, result: ChannelResult) -> None:
        self._result = result

    def set_raises(self, exc: Exception | None) -> None:
        self._raises = exc

    def bodies(self) -> list[str]:
        return [key for _, key in self.calls]


class FakeTelegramSender:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.sent: list[tuple[int, str]] = []
        self.raises = raises

    def send_message(self, *, chat_id: int, text: str, action: str | None = None):
        if self.raises is not None:
            raise self.raises
        self.sent.append((chat_id, text))


class FakeChatIds:
    def __init__(self, mapping: dict[int, int] | None = None) -> None:
        self.mapping = mapping if mapping is not None else {USER_ID: 555}

    def telegram_id(self, user_id: int) -> int | None:
        return self.mapping.get(user_id)


def subscription(
    *,
    subscription_id: str = "sub-1",
    user_id: int = USER_ID,
    plan_name: str = "Geek Turbo",
    days_from: int = 3,
    used_gib: float = 0.0,
    total_gib: float | None = 100.0,
    active: bool = True,
    now: datetime = EPOCH,
) -> SubscriptionSnapshot:
    """Builder so tests state only the fact they care about."""
    return SubscriptionSnapshot(
        subscription_id=subscription_id,
        user_id=user_id,
        plan_name=plan_name,
        expires_at=now + timedelta(days=days_from),
        used_gib=used_gib,
        total_gib=total_gib,
        active=active,
    )


def campaign(
    *,
    campaign_id: str = "cmp-1",
    percent: int = 30,
    now: datetime = EPOCH,
    live: bool = True,
    announced: bool = False,
) -> CampaignSnapshot:
    start = now - timedelta(days=1) if live else now + timedelta(days=1)
    return CampaignSnapshot(
        campaign_id=campaign_id,
        title_fa="\u062c\u0634\u0646\u0648\u0627\u0631\u0647\u0654 \u062a\u0627\u0628\u0633\u062a\u0627\u0646",
        discount_percent=percent,
        starts_at=start,
        ends_at=start + timedelta(days=7),
        audience=AudienceKind.ALL,
        audience_ref=None,
        announced=announced,
    )


__all__ = [
    "ADMIN_ID",
    "EPOCH",
    "QUIET_EPOCH",
    "USER_ID",
    "FakeAudience",
    "FakeBroadcastRepository",
    "FakeCampaigns",
    "FakeChatIds",
    "FakeClock",
    "FakeEvents",
    "FakeIds",
    "FakeNotificationRepository",
    "FakePreferences",
    "FakeSubscriptions",
    "FakeTelegramSender",
    "RecordingChannel",
    "campaign",
    "subscription",
]
