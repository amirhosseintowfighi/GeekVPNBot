"""Notification application layer.

One engine, two channels, five scheduled jobs, and the event handlers that
turn payment and support facts into Persian messages.
"""

from geekvpn.application.notifications.broadcast_service import (
    BroadcastProgress,
    BroadcastService,
)
from geekvpn.application.notifications.campaign_service import (
    CampaignAnnouncement,
    CampaignService,
)
from geekvpn.application.notifications.channels import (
    ChatIdResolver,
    InboxChannel,
    TelegramChannel,
    TelegramSender,
)
from geekvpn.application.notifications.engine import (
    DEFAULT_CHANNELS,
    MARKETING_DAILY_CAP,
    DispatchResult,
    NotificationEngine,
)
from geekvpn.application.notifications.inbox_service import (
    PAGE_SIZE,
    InboxItem,
    InboxPage,
    InboxService,
)
from geekvpn.application.notifications.ports import (
    AudienceResolver,
    BroadcastRepository,
    CampaignReader,
    CampaignSnapshot,
    Channel,
    ChannelResult,
    Clock,
    EventPublisher,
    IdGenerator,
    NotificationRepository,
    NotificationServices,
    PreferencesStore,
    SubscriptionReader,
    SubscriptionSnapshot,
)
from geekvpn.application.notifications.reminders import ReminderService, SweepReport
from geekvpn.application.notifications.scheduler import (
    JobRun,
    NotificationScheduler,
    TickReport,
)
from geekvpn.application.notifications.subscribers import (
    EngineSupportNotifier,
    PurchaseNotifications,
    WalletNotifications,
    register,
)

__all__ = [
    "DEFAULT_CHANNELS",
    "MARKETING_DAILY_CAP",
    "PAGE_SIZE",
    "AudienceResolver",
    "BroadcastProgress",
    "BroadcastRepository",
    "BroadcastService",
    "CampaignAnnouncement",
    "CampaignReader",
    "CampaignService",
    "CampaignSnapshot",
    "Channel",
    "ChannelResult",
    "ChatIdResolver",
    "Clock",
    "DispatchResult",
    "EngineSupportNotifier",
    "EventPublisher",
    "IdGenerator",
    "InboxChannel",
    "InboxItem",
    "InboxPage",
    "InboxService",
    "JobRun",
    "NotificationEngine",
    "NotificationRepository",
    "NotificationScheduler",
    "NotificationServices",
    "PreferencesStore",
    "PurchaseNotifications",
    "ReminderService",
    "SubscriptionReader",
    "SubscriptionSnapshot",
    "SweepReport",
    "TelegramChannel",
    "TelegramSender",
    "TickReport",
    "WalletNotifications",
    "register",
]
