"""Notification enums.

The engine separates three orthogonal ideas that the old bot-only notifier
conflated:

- **Category** is *why* we are writing. It maps to a user preference switch
  and decides whether quiet hours apply.
- **Channel** is *where* it goes. Telegram is a push; the Mini App inbox is a
  pull. A single notification can target both, and failure on one must not
  cancel the other.
- **DeliveryState** is *what happened* on one channel. Suppression is a
  first-class outcome, not an error: "the user muted promotions" is a normal
  business fact that the admin panel must be able to report on.
"""

from __future__ import annotations

import enum


class NotificationCategory(enum.StrEnum):
    """Why we are contacting the customer.

    ``CRITICAL`` is reserved for transactional facts the customer is entitled
    to receive: their money moved, their service died, an operator replied.
    It cannot be muted and it ignores quiet hours. Everything else can be
    switched off, which is what keeps the bot from being blocked.
    """

    EXPIRY = "expiry"
    TRAFFIC = "traffic"
    PROMOS = "promos"
    NEWS = "news"
    CRITICAL = "critical"

    @property
    def bypasses_quiet_hours(self) -> bool:
        return self is NotificationCategory.CRITICAL

    @property
    def preference_key(self) -> str | None:
        """The preference switch governing this category, or None if unmutable."""
        return None if self is NotificationCategory.CRITICAL else self.value

    @property
    def is_marketing(self) -> bool:
        """Marketing categories are rate-limited per user per day."""
        return self in (NotificationCategory.PROMOS, NotificationCategory.NEWS)

    def label_fa(self) -> str:
        return {
            NotificationCategory.EXPIRY: "\u0627\u0646\u0642\u0636\u0627",
            NotificationCategory.TRAFFIC: "\u062d\u062c\u0645 \u0645\u0635\u0631\u0641\u06cc",
            NotificationCategory.PROMOS: "\u067e\u06cc\u0634\u0646\u0647\u0627\u062f\u0647\u0627",
            NotificationCategory.NEWS: "\u0627\u062e\u0628\u0627\u0631",
            NotificationCategory.CRITICAL: "\u0645\u0647\u0645",
        }[self]


class NotificationChannel(enum.StrEnum):
    """Where a notification is delivered.

    TELEGRAM is a push and can fail for reasons outside our control (the user
    blocked the bot). MINIAPP is an inbox row we own, so it effectively never
    fails -- which is exactly why every notification is written there, giving
    the customer a place to find what they missed while the bot was blocked.
    """

    TELEGRAM = "telegram"
    MINIAPP = "miniapp"

    def label_fa(self) -> str:
        return {
            NotificationChannel.TELEGRAM: "\u062a\u0644\u06af\u0631\u0627\u0645",
            NotificationChannel.MINIAPP: "\u0645\u06cc\u0646\u06cc\u200c\u0627\u067e",
        }[self]


class DeliveryState(enum.StrEnum):
    """Outcome of one attempt on one channel."""

    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    SUPPRESSED = "suppressed"
    DEFERRED = "deferred"

    def is_terminal(self) -> bool:
        """DEFERRED is not terminal: a quiet-hours notice is retried at dawn."""
        return self in (
            DeliveryState.SENT,
            DeliveryState.FAILED,
            DeliveryState.SUPPRESSED,
        )

    def is_success(self) -> bool:
        return self is DeliveryState.SENT

    def label_fa(self) -> str:
        return {
            DeliveryState.PENDING: "\u062f\u0631 \u0635\u0641",
            DeliveryState.SENT: "\u0627\u0631\u0633\u0627\u0644 \u0634\u062f",
            DeliveryState.FAILED: "\u0646\u0627\u0645\u0648\u0641\u0642",
            DeliveryState.SUPPRESSED: "\u0645\u0633\u062f\u0648\u062f \u0634\u062f\u0647",
            DeliveryState.DEFERRED: "\u0628\u0647 \u062a\u0639\u0648\u06cc\u0642 \u0627\u0641\u062a\u0627\u062f",
        }[self]


class SuppressionReason(enum.StrEnum):
    """Why a notification was not delivered.

    Recorded rather than discarded. "Why did the customer not get the expiry
    warning?" must be answerable from data, not guesswork.
    """

    MUTED = "muted"
    QUIET_HOURS = "quiet_hours"
    NO_CHAT_ID = "no_chat_id"
    BLOCKED = "blocked"
    DUPLICATE = "duplicate"
    RATE_LIMITED = "rate_limited"
    CHANNEL_DISABLED = "channel_disabled"

    def label_fa(self) -> str:
        return {
            SuppressionReason.MUTED: "\u06a9\u0627\u0631\u0628\u0631 \u062e\u0627\u0645\u0648\u0634 \u06a9\u0631\u062f\u0647",
            SuppressionReason.QUIET_HOURS: "\u0633\u0627\u0639\u0627\u062a \u0633\u06a9\u0648\u062a",
            SuppressionReason.NO_CHAT_ID: "\u0634\u0646\u0627\u0633\u0647\u0654 \u06af\u0641\u062a\u06af\u0648 \u0646\u062f\u0627\u0631\u062f",
            SuppressionReason.BLOCKED: "\u0631\u0628\u0627\u062a \u0645\u0633\u062f\u0648\u062f \u0634\u062f\u0647",
            SuppressionReason.DUPLICATE: "\u062a\u06a9\u0631\u0627\u0631\u06cc",
            SuppressionReason.RATE_LIMITED: "\u0645\u062d\u062f\u0648\u062f\u06cc\u062a \u062a\u0639\u062f\u0627\u062f",
            SuppressionReason.CHANNEL_DISABLED: "\u06a9\u0627\u0646\u0627\u0644 \u063a\u06cc\u0631\u0641\u0639\u0627\u0644",
        }[self]


class BroadcastState(enum.StrEnum):
    """Lifecycle of an admin broadcast.

    Mirrors ``admin/src/lib/labels.ts::BROADCAST_STATE`` exactly so the panel
    never displays a state the backend cannot produce.
    """

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENDING = "sending"
    SENT = "sent"
    CANCELLED = "cancelled"
    FAILED = "failed"

    def is_terminal(self) -> bool:
        return self in (
            BroadcastState.SENT,
            BroadcastState.CANCELLED,
            BroadcastState.FAILED,
        )

    def is_editable(self) -> bool:
        """Once sending has begun the copy is frozen; half the audience has it."""
        return self in (BroadcastState.DRAFT, BroadcastState.SCHEDULED)

    def label_fa(self) -> str:
        return {
            BroadcastState.DRAFT: "\u067e\u06cc\u0634\u200c\u0646\u0648\u06cc\u0633",
            BroadcastState.SCHEDULED: "\u0632\u0645\u0627\u0646\u200c\u0628\u0646\u062f\u06cc \u0634\u062f\u0647",
            BroadcastState.SENDING: "\u062f\u0631 \u062d\u0627\u0644 \u0627\u0631\u0633\u0627\u0644",
            BroadcastState.SENT: "\u0627\u0631\u0633\u0627\u0644 \u0634\u062f\u0647",
            BroadcastState.CANCELLED: "\u0644\u063a\u0648 \u0634\u062f\u0647",
            BroadcastState.FAILED: "\u0646\u0627\u0645\u0648\u0641\u0642",
        }[self]


class AudienceKind(enum.StrEnum):
    """Who a broadcast or campaign announcement targets."""

    ALL = "all"
    ACTIVE_SUBSCRIBERS = "active_subscribers"
    EXPIRED = "expired"
    EXPIRING_SOON = "expiring_soon"
    NEVER_PURCHASED = "never_purchased"
    TIER = "tier"
    EXPLICIT = "explicit"

    def label_fa(self) -> str:
        return {
            AudienceKind.ALL: "\u0647\u0645\u0647\u0654 \u06a9\u0627\u0631\u0628\u0631\u0627\u0646",
            AudienceKind.ACTIVE_SUBSCRIBERS: "\u0645\u0634\u062a\u0631\u06a9\u0627\u0646 \u0641\u0639\u0627\u0644",
            AudienceKind.EXPIRED: "\u0645\u0646\u0642\u0636\u06cc \u0634\u062f\u0647",
            AudienceKind.EXPIRING_SOON: "\u0646\u0632\u062f\u06cc\u06a9 \u0628\u0647 \u0627\u0646\u0642\u0636\u0627",
            AudienceKind.NEVER_PURCHASED: "\u0628\u062f\u0648\u0646 \u062e\u0631\u06cc\u062f",
            AudienceKind.TIER: "\u0633\u0637\u062d \u0648\u0641\u0627\u062f\u0627\u0631\u06cc",
            AudienceKind.EXPLICIT: "\u0641\u0647\u0631\u0633\u062a \u062f\u0633\u062a\u06cc",
        }[self]


class JobKind(enum.StrEnum):
    """The scheduled jobs the engine knows how to run."""

    EXPIRATION_REMINDER = "expiration_reminder"
    TRAFFIC_REMINDER = "traffic_reminder"
    IDLE_NUDGE = "idle_nudge"
    BROADCAST_DISPATCH = "broadcast_dispatch"
    CAMPAIGN_ANNOUNCE = "campaign_announce"
    DEFERRED_FLUSH = "deferred_flush"

    def label_fa(self) -> str:
        return {
            JobKind.EXPIRATION_REMINDER: "\u06cc\u0627\u062f\u0622\u0648\u0631\u06cc \u0627\u0646\u0642\u0636\u0627",
            JobKind.TRAFFIC_REMINDER: "\u06cc\u0627\u062f\u0622\u0648\u0631\u06cc \u062d\u062c\u0645",
            JobKind.IDLE_NUDGE: "پیگیری عدم اتصال",
            JobKind.BROADCAST_DISPATCH: "\u0627\u0631\u0633\u0627\u0644 \u0647\u0645\u06af\u0627\u0646\u06cc",
            JobKind.CAMPAIGN_ANNOUNCE: "\u0627\u0639\u0644\u0627\u0646 \u06a9\u0645\u067e\u06cc\u0646",
            JobKind.DEFERRED_FLUSH: "\u0627\u0631\u0633\u0627\u0644 \u0645\u0639\u0648\u0642\u0647",
        }[self]


__all__ = [
    "AudienceKind",
    "BroadcastState",
    "DeliveryState",
    "JobKind",
    "NotificationCategory",
    "NotificationChannel",
    "SuppressionReason",
]
