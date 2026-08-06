"""Notification domain events.

Naming: notify.<thing>.<past_tense>.v1

Suppression gets its own event on purpose. "We decided not to contact this
customer, and here is why" is an auditable business decision, and it is the
only way support can answer "why didn't I get the expiry warning?".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

from geekvpn.domain.base.events import DomainEvent
from geekvpn.domain.notifications.enums import (
    JobKind,
    NotificationCategory,
    NotificationChannel,
    SuppressionReason,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationQueued(DomainEvent):
    """A rendered message was accepted by the engine."""

    name: ClassVar[str] = "notify.notification.queued.v1"

    notification_id: str
    user_id: int
    category: NotificationCategory
    template_key: str
    channels: tuple[NotificationChannel, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "user_id": self.user_id,
            "category": str(self.category),
            "template_key": self.template_key,
            "channels": [str(c) for c in self.channels],
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationSent(DomainEvent):
    """One channel accepted the message."""

    name: ClassVar[str] = "notify.notification.sent.v1"

    notification_id: str
    user_id: int
    channel: NotificationChannel
    category: NotificationCategory

    def payload(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "user_id": self.user_id,
            "channel": str(self.channel),
            "category": str(self.category),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationSuppressed(DomainEvent):
    """We chose not to deliver, and this is the reason."""

    name: ClassVar[str] = "notify.notification.suppressed.v1"

    notification_id: str
    user_id: int
    channel: NotificationChannel
    category: NotificationCategory
    reason: SuppressionReason

    def payload(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "user_id": self.user_id,
            "channel": str(self.channel),
            "category": str(self.category),
            "reason": str(self.reason),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationFailed(DomainEvent):
    """The channel raised. Distinct from suppression: this one may be retried."""

    name: ClassVar[str] = "notify.notification.failed.v1"

    notification_id: str
    user_id: int
    channel: NotificationChannel
    error: str
    attempts: int

    def payload(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "user_id": self.user_id,
            "channel": str(self.channel),
            "error": self.error,
            "attempts": self.attempts,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationDeferred(DomainEvent):
    """Held for quiet hours; will be flushed at ``send_after``."""

    name: ClassVar[str] = "notify.notification.deferred.v1"

    notification_id: str
    user_id: int
    channel: NotificationChannel
    send_after: datetime

    def payload(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "user_id": self.user_id,
            "channel": str(self.channel),
            "send_after": self.send_after.isoformat(),
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationRead(DomainEvent):
    """The customer opened it in the Mini App inbox."""

    name: ClassVar[str] = "notify.notification.read.v1"

    notification_id: str
    user_id: int

    def payload(self) -> dict[str, Any]:
        return {"notification_id": self.notification_id, "user_id": self.user_id}


@dataclass(frozen=True, slots=True, kw_only=True)
class BroadcastScheduled(DomainEvent):
    name: ClassVar[str] = "notify.broadcast.scheduled.v1"

    broadcast_id: str
    title_fa: str
    send_at: datetime
    audience: str

    def payload(self) -> dict[str, Any]:
        return {
            "broadcast_id": self.broadcast_id,
            "title_fa": self.title_fa,
            "send_at": self.send_at.isoformat(),
            "audience": self.audience,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class BroadcastStarted(DomainEvent):
    name: ClassVar[str] = "notify.broadcast.started.v1"

    broadcast_id: str
    recipient_count: int

    def payload(self) -> dict[str, Any]:
        return {
            "broadcast_id": self.broadcast_id,
            "recipient_count": self.recipient_count,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class BroadcastCompleted(DomainEvent):
    name: ClassVar[str] = "notify.broadcast.completed.v1"

    broadcast_id: str
    sent: int
    suppressed: int
    failed: int

    def payload(self) -> dict[str, Any]:
        return {
            "broadcast_id": self.broadcast_id,
            "sent": self.sent,
            "suppressed": self.suppressed,
            "failed": self.failed,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class BroadcastCancelled(DomainEvent):
    name: ClassVar[str] = "notify.broadcast.cancelled.v1"

    broadcast_id: str
    cancelled_by: int
    sent_before_cancel: int

    def payload(self) -> dict[str, Any]:
        return {
            "broadcast_id": self.broadcast_id,
            "cancelled_by": self.cancelled_by,
            "sent_before_cancel": self.sent_before_cancel,
        }


@dataclass(frozen=True, slots=True, kw_only=True)
class ReminderJobCompleted(DomainEvent):
    """A scheduled sweep finished. Feeds the admin panel's job health view."""

    name: ClassVar[str] = "notify.job.completed.v1"

    job: JobKind
    examined: int
    queued: int
    skipped: int

    def payload(self) -> dict[str, Any]:
        return {
            "job": str(self.job),
            "examined": self.examined,
            "queued": self.queued,
            "skipped": self.skipped,
        }


__all__ = [
    "BroadcastCancelled",
    "BroadcastCompleted",
    "BroadcastScheduled",
    "BroadcastStarted",
    "NotificationDeferred",
    "NotificationFailed",
    "NotificationQueued",
    "NotificationRead",
    "NotificationSent",
    "NotificationSuppressed",
    "ReminderJobCompleted",
]
