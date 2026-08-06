"""The Notification aggregate.

One notification is one *decision to contact a customer*, fanned out over one
or more channels. Per-channel outcomes are tracked separately because they
genuinely differ: Telegram can be blocked while the Mini App inbox row is
written fine, and the customer is then still informed.

The aggregate is the audit trail. Nothing is thrown away -- a suppressed
notification is stored with its reason, which is what lets support answer
"why didn't I get the warning?" from data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from geekvpn.domain.base.entity import AggregateRoot
from geekvpn.domain.notifications.enums import (
    DeliveryState,
    NotificationCategory,
    NotificationChannel,
    SuppressionReason,
)
from geekvpn.domain.notifications.events import (
    NotificationDeferred,
    NotificationFailed,
    NotificationQueued,
    NotificationRead,
    NotificationSent,
    NotificationSuppressed,
)
from geekvpn.domain.notifications.message import RenderedMessage

# Telegram failures are usually permanent (blocked bot) rather than transient,
# so the retry budget is small on purpose.
MAX_ATTEMPTS = 3


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    """The current outcome on one channel."""

    channel: NotificationChannel
    state: DeliveryState = DeliveryState.PENDING
    reason: SuppressionReason | None = None
    error: str = ""
    attempts: int = 0
    send_after: datetime | None = None
    updated_at: datetime | None = None

    def is_retryable(self) -> bool:
        """Only genuine failures retry; a muted user is not retried at all."""
        return self.state is DeliveryState.FAILED and self.attempts < MAX_ATTEMPTS


class Notification(AggregateRoot[str]):
    """A rendered Persian message plus its per-channel delivery record."""

    __slots__ = (
        "_deliveries",
        "created_at",
        "dedupe_key",
        "message",
        "read_at",
        "source",
        "user_id",
    )

    def __init__(
        self,
        notification_id: str,
        *,
        user_id: int,
        message: RenderedMessage,
        channels: tuple[NotificationChannel, ...],
        created_at: datetime,
        dedupe_key: str | None = None,
        source: str | None = None,
    ) -> None:
        super().__init__(notification_id)
        self.user_id = user_id
        self.message = message
        self.created_at = created_at
        self.read_at: datetime | None = None
        self.dedupe_key = dedupe_key
        self.source = source
        self._deliveries: dict[NotificationChannel, DeliveryAttempt] = {
            channel: DeliveryAttempt(channel=channel) for channel in channels
        }

    # ---- Construction ---------------------------------------------------

    @classmethod
    def queue(
        cls,
        notification_id: str,
        *,
        user_id: int,
        message: RenderedMessage,
        channels: tuple[NotificationChannel, ...],
        now: datetime,
        dedupe_key: str | None = None,
        source: str | None = None,
    ) -> Notification:
        notification = cls(
            notification_id,
            user_id=user_id,
            message=message,
            channels=channels,
            created_at=now,
            dedupe_key=dedupe_key,
            source=source,
        )
        notification.record(
            NotificationQueued(
                notification_id=notification_id,
                user_id=user_id,
                category=message.category,
                template_key=message.key,
                channels=channels,
            )
        )
        return notification

    @classmethod
    def restore(
        cls,
        notification_id: str,
        *,
        user_id: int,
        message: RenderedMessage,
        deliveries: Sequence[DeliveryAttempt],
        created_at: datetime,
        read_at: datetime | None = None,
        dedupe_key: str | None = None,
        source: str | None = None,
    ) -> Notification:
        """Rebuild a notification exactly as it was stored.

        Distinct from ``queue`` on purpose: loading a row is not a business
        event, so this records nothing. If rehydration emitted
        ``NotificationQueued``, every restart would re-send the backlog.
        """
        notification = cls(
            notification_id,
            user_id=user_id,
            message=message,
            channels=tuple(attempt.channel for attempt in deliveries),
            created_at=created_at,
            dedupe_key=dedupe_key,
            source=source,
        )
        notification._deliveries = {attempt.channel: attempt for attempt in deliveries}
        notification.read_at = read_at
        return notification

    # ---- Accessors ------------------------------------------------------

    @property
    def category(self) -> NotificationCategory:
        return self.message.category

    @property
    def channels(self) -> tuple[NotificationChannel, ...]:
        return tuple(self._deliveries)

    def deliveries(self) -> tuple[DeliveryAttempt, ...]:
        return tuple(self._deliveries.values())

    def delivery_for(self, channel: NotificationChannel) -> DeliveryAttempt | None:
        return self._deliveries.get(channel)

    def state_for(self, channel: NotificationChannel) -> DeliveryState | None:
        attempt = self._deliveries.get(channel)
        return attempt.state if attempt else None

    def is_delivered_anywhere(self) -> bool:
        return any(a.state.is_success() for a in self._deliveries.values())

    def is_settled(self) -> bool:
        """True once no channel is still pending or waiting out quiet hours."""
        return all(a.state.is_terminal() for a in self._deliveries.values())

    def is_unread(self) -> bool:
        return self.read_at is None

    def pending_channels(self) -> tuple[NotificationChannel, ...]:
        return tuple(
            channel
            for channel, attempt in self._deliveries.items()
            if attempt.state is DeliveryState.PENDING
        )

    def due_channels(self, now: datetime) -> tuple[NotificationChannel, ...]:
        """Deferred channels whose quiet window has passed, plus pending ones."""
        due: list[NotificationChannel] = []
        for channel, attempt in self._deliveries.items():
            if attempt.state is DeliveryState.PENDING or (
                attempt.state is DeliveryState.DEFERRED
                and (attempt.send_after is None or attempt.send_after <= now)
            ):
                due.append(channel)
        return tuple(due)

    # ---- Transitions ----------------------------------------------------

    def _replace(self, channel: NotificationChannel, **changes: object) -> None:
        current = self._deliveries.get(channel)
        if current is None:
            current = DeliveryAttempt(channel=channel)
        merged = {
            "channel": channel,
            "state": current.state,
            "reason": current.reason,
            "error": current.error,
            "attempts": current.attempts,
            "send_after": current.send_after,
            "updated_at": current.updated_at,
        }
        merged.update(changes)
        self._deliveries[channel] = DeliveryAttempt(**merged)  # type: ignore[arg-type]

    def mark_sent(self, channel: NotificationChannel, *, now: datetime) -> None:
        current = self._deliveries.get(channel)
        attempts = (current.attempts if current else 0) + 1
        self._replace(
            channel,
            state=DeliveryState.SENT,
            reason=None,
            error="",
            attempts=attempts,
            send_after=None,
            updated_at=now,
        )
        self.record(
            NotificationSent(
                notification_id=self.id,
                user_id=self.user_id,
                channel=channel,
                category=self.category,
            )
        )

    def mark_suppressed(
        self,
        channel: NotificationChannel,
        *,
        reason: SuppressionReason,
        now: datetime,
    ) -> None:
        self._replace(
            channel,
            state=DeliveryState.SUPPRESSED,
            reason=reason,
            send_after=None,
            updated_at=now,
        )
        self.record(
            NotificationSuppressed(
                notification_id=self.id,
                user_id=self.user_id,
                channel=channel,
                category=self.category,
                reason=reason,
            )
        )

    def mark_failed(self, channel: NotificationChannel, *, error: str, now: datetime) -> None:
        current = self._deliveries.get(channel)
        attempts = (current.attempts if current else 0) + 1
        self._replace(
            channel,
            state=DeliveryState.FAILED,
            error=error,
            attempts=attempts,
            send_after=None,
            updated_at=now,
        )
        self.record(
            NotificationFailed(
                notification_id=self.id,
                user_id=self.user_id,
                channel=channel,
                error=error,
                attempts=attempts,
            )
        )

    def defer(self, channel: NotificationChannel, *, send_after: datetime, now: datetime) -> None:
        self._replace(
            channel,
            state=DeliveryState.DEFERRED,
            reason=SuppressionReason.QUIET_HOURS,
            send_after=send_after,
            updated_at=now,
        )
        self.record(
            NotificationDeferred(
                notification_id=self.id,
                user_id=self.user_id,
                channel=channel,
                send_after=send_after,
            )
        )

    def mark_read(self, *, now: datetime) -> bool:
        """Idempotent. Returns True only on the first read.

        The Mini App calls this on every inbox open, so a second call must not
        emit a second event or the unread badge analytics would double count.
        """
        if self.read_at is not None:
            return False
        self.read_at = now
        self.record(NotificationRead(notification_id=self.id, user_id=self.user_id))
        return True


__all__ = ["MAX_ATTEMPTS", "DeliveryAttempt", "Notification"]
