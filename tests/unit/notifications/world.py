"""Wired world for notification tests. One instance per test."""

from __future__ import annotations

from datetime import datetime

from geekvpn.application.notifications.broadcast_service import BroadcastService
from geekvpn.application.notifications.campaign_service import CampaignService
from geekvpn.application.notifications.engine import NotificationEngine
from geekvpn.application.notifications.inbox_service import InboxService
from geekvpn.application.notifications.reminders import ReminderService
from geekvpn.application.notifications.scheduler import NotificationScheduler
from geekvpn.application.notifications.subscribers import (
    PurchaseNotifications,
    WalletNotifications,
)
from geekvpn.domain.notifications.enums import NotificationChannel
from geekvpn.domain.notifications.preferences import NotificationPreferences
from tests.unit.notifications.fakes import (
    EPOCH,
    USER_ID,
    FakeAudience,
    FakeBroadcastRepository,
    FakeCampaigns,
    FakeClock,
    FakeEvents,
    FakeIds,
    FakeNotificationRepository,
    FakePreferences,
    FakeSubscriptions,
    RecordingChannel,
)


class World:
    def __init__(self, *, now: datetime = EPOCH, batch_size: int = 25) -> None:
        self.clock = FakeClock(now)
        self.ids = FakeIds()
        self.events = FakeEvents()
        self.preferences = FakePreferences()
        self.repo = FakeNotificationRepository()
        self.broadcast_repo = FakeBroadcastRepository()
        self.audience = FakeAudience()
        self.subscriptions = FakeSubscriptions()
        self.campaign_reader = FakeCampaigns()

        self.telegram = RecordingChannel(NotificationChannel.TELEGRAM)
        self.miniapp = RecordingChannel(NotificationChannel.MINIAPP)

        self.engine = NotificationEngine(
            notifications=self.repo,
            preferences=self.preferences,
            channels=[self.telegram, self.miniapp],
            clock=self.clock,
            ids=self.ids,
            events=self.events,
        )
        self.reminders = ReminderService(
            engine=self.engine,
            subscriptions=self.subscriptions,
            clock=self.clock,
            events=self.events,
        )
        self.broadcasts = BroadcastService(
            engine=self.engine,
            broadcasts=self.broadcast_repo,
            audiences=self.audience,
            clock=self.clock,
            ids=self.ids,
            events=self.events,
            batch_size=batch_size,
        )
        self.campaigns = CampaignService(
            engine=self.engine,
            campaigns=self.campaign_reader,
            audiences=self.audience,
            clock=self.clock,
            events=self.events,
        )
        self.inbox = InboxService(
            notifications=self.repo,
            clock=self.clock,
            events=self.events,
        )
        self.scheduler = NotificationScheduler(clock=self.clock)
        self.wallet = WalletNotifications(engine=self.engine)
        self.purchases = PurchaseNotifications(engine=self.engine)

    # ---- Helpers --------------------------------------------------------

    def mute(self, key: str, *, user_id: int = USER_ID) -> None:
        current = self.preferences.load(user_id)
        self.preferences.set_for(user_id, current.with_toggled(key))

    def set_preferences(
        self, preferences: NotificationPreferences, *, user_id: int = USER_ID
    ) -> None:
        self.preferences.set_for(user_id, preferences)

    def notify(self, key: str = "expiry.soon", **fields):
        payload = {"plan": "Geek Turbo", "days": 3}
        payload.update(fields)
        return self.engine.notify(
            user_id=payload.pop("user_id", USER_ID),
            template_key=key,
            fields=payload,
        )

    def stored(self):
        return list(self.repo.rows.values())

    def only(self):
        rows = self.stored()
        assert len(rows) == 1, f"expected exactly one notification, got {len(rows)}"
        return rows[0]


__all__ = ["World"]
