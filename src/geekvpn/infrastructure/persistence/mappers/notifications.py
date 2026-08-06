"""Mappers between the notification tables and the notification aggregates.

Per-channel delivery lives in a JSONB column rather than its own table. The
channel set is small and fixed (Telegram, Mini App), a notification is always
loaded whole, and nothing ever queries "all Telegram attempts" across users -
so a child table would buy a join and sell nothing.

The scalar ``state`` column is a *summary* of those attempts, written for the
scheduler's index and never read back into the aggregate. Deriving it on save
keeps one source of truth: the attempts.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from geekvpn.domain.notifications.broadcast import Broadcast
from geekvpn.domain.notifications.enums import (
    AudienceKind,
    BroadcastState,
    DeliveryState,
    JobKind,
    NotificationCategory,
    NotificationChannel,
    SuppressionReason,
)
from geekvpn.domain.notifications.message import RenderedMessage
from geekvpn.domain.notifications.notification import DeliveryAttempt, Notification
from geekvpn.domain.notifications.preferences import (
    ChannelPreferences,
    NotificationPreferences,
    QuietHours,
)
from geekvpn.domain.notifications.schedule import ScheduleEntry
from geekvpn.infrastructure.persistence.models.notifications import (
    BroadcastModel,
    NotificationModel,
    NotificationPreferenceModel,
    ScheduledJobModel,
)

#: Worst-to-best. Used to summarise per-channel attempts into one column: a
#: notification that reached any channel counts as delivered, because that is
#: what "did the customer hear from us?" means.
_STATE_RANK: tuple[DeliveryState, ...] = (
    DeliveryState.SENT,
    DeliveryState.PENDING,
    DeliveryState.DEFERRED,
    DeliveryState.FAILED,
    DeliveryState.SUPPRESSED,
)


# -- delivery attempts -----------------------------------------------------


def attempt_to_json(attempt: DeliveryAttempt) -> dict[str, Any]:
    return {
        "channel": attempt.channel.value,
        "state": attempt.state.value,
        "reason": attempt.reason.value if attempt.reason else None,
        "error": attempt.error,
        "attempts": attempt.attempts,
        "send_after": attempt.send_after.isoformat() if attempt.send_after else None,
        "updated_at": attempt.updated_at.isoformat() if attempt.updated_at else None,
    }


def attempt_from_json(raw: dict[str, Any]) -> DeliveryAttempt:
    return DeliveryAttempt(
        channel=NotificationChannel(raw["channel"]),
        state=DeliveryState(raw.get("state", DeliveryState.PENDING.value)),
        reason=SuppressionReason(raw["reason"]) if raw.get("reason") else None,
        error=raw.get("error", ""),
        attempts=int(raw.get("attempts", 0)),
        send_after=_parse(raw.get("send_after")),
        updated_at=_parse(raw.get("updated_at")),
    )


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def summarise_state(attempts: Sequence[DeliveryAttempt]) -> DeliveryState:
    """Collapse per-channel outcomes into the one column the scheduler scans."""
    if not attempts:
        return DeliveryState.PENDING
    states = {attempt.state for attempt in attempts}
    for candidate in _STATE_RANK:
        if candidate in states:
            return candidate
    return DeliveryState.PENDING


def earliest_send_after(attempts: Sequence[DeliveryAttempt]) -> datetime | None:
    """When the scheduler should look at this row again."""
    times = [
        attempt.send_after
        for attempt in attempts
        if attempt.send_after is not None and attempt.state is DeliveryState.DEFERRED
    ]
    return min(times) if times else None


# -- notification ----------------------------------------------------------


def notification_to_domain(model: NotificationModel) -> Notification:
    return Notification.restore(
        model.id,
        user_id=model.user_id,
        message=RenderedMessage(
            key=model.template_key,
            category=NotificationCategory(model.category),
            title_fa=model.title_fa,
            body_fa=model.body_fa,
            action=model.action,
        ),
        deliveries=[attempt_from_json(raw) for raw in (model.deliveries or [])],
        created_at=model.queued_at,
        read_at=model.read_at,
        dedupe_key=model.dedupe_key,
        source=model.source,
    )


def notification_apply(
    model: NotificationModel,
    notification: Notification,
    *,
    broadcast_id: str | None = None,
) -> NotificationModel:
    attempts = list(notification.deliveries())
    message = notification.message
    model.category = message.category.value
    model.template_key = message.key
    model.title_fa = message.title_fa
    model.body_fa = message.body_fa
    model.action = message.action
    model.deliveries = [attempt_to_json(attempt) for attempt in attempts]
    model.state = summarise_state(attempts).value
    model.queued_at = notification.created_at
    model.send_after = earliest_send_after(attempts)
    model.read_at = notification.read_at
    model.dedupe_key = notification.dedupe_key
    model.source = notification.source
    if broadcast_id is not None:
        model.broadcast_id = broadcast_id
    return model


def notification_to_row(
    notification: Notification, *, broadcast_id: str | None = None
) -> NotificationModel:
    model = NotificationModel(id=notification.id, user_id=notification.user_id)
    return notification_apply(model, notification, broadcast_id=broadcast_id)


# -- preferences -----------------------------------------------------------


def preferences_to_domain(
    model: NotificationPreferenceModel | None,
) -> NotificationPreferences:
    """Absent row means defaults.

    Every user who never opened settings has no row, and defaulting here keeps
    the caller from having to decide what silence means.
    """
    if model is None:
        return NotificationPreferences()
    return NotificationPreferences(
        expiry=model.expiry,
        traffic=model.traffic,
        promos=model.promos,
        news=model.news,
        quiet=QuietHours(
            start_hour=model.quiet_start_hour,
            end_hour=model.quiet_end_hour,
            enabled=model.quiet_enabled,
        ),
        channels=ChannelPreferences(telegram=model.telegram, miniapp=model.miniapp),
    )


def preferences_apply(
    model: NotificationPreferenceModel, prefs: NotificationPreferences
) -> NotificationPreferenceModel:
    model.expiry = prefs.expiry
    model.traffic = prefs.traffic
    model.promos = prefs.promos
    model.news = prefs.news
    model.telegram = prefs.channels.telegram
    model.miniapp = prefs.channels.miniapp
    model.quiet_enabled = prefs.quiet.enabled
    model.quiet_start_hour = prefs.quiet.start_hour
    model.quiet_end_hour = prefs.quiet.end_hour
    return model


def preferences_to_row(user_id: int, prefs: NotificationPreferences) -> NotificationPreferenceModel:
    return preferences_apply(NotificationPreferenceModel(user_id=user_id), prefs)


# -- broadcast -------------------------------------------------------------


def broadcast_to_domain(model: BroadcastModel) -> Broadcast:
    audience_filter = model.audience_filter or {}
    return Broadcast.restore(
        model.id,
        title_fa=model.title_fa,
        body_fa=model.body_fa,
        audience=AudienceKind(model.audience_kind),
        created_by=model.created_by or 0,
        created_at=model.created_at,
        state=BroadcastState(model.state),
        category=NotificationCategory(model.category),
        audience_ref=audience_filter.get("ref"),
        send_at=model.scheduled_for,
        started_at=model.started_at,
        finished_at=model.finished_at,
        recipient_count=model.recipient_count,
        sent=model.sent_count,
        suppressed=model.suppressed_count,
        failed=model.failed_count,
        error=model.error or "",
    )


def broadcast_apply(model: BroadcastModel, broadcast: Broadcast) -> BroadcastModel:
    model.title_fa = broadcast.title_fa
    model.body_fa = broadcast.body_fa
    model.category = broadcast.category.value
    model.state = broadcast.state.value
    model.audience_kind = broadcast.audience.value
    # A JSONB object rather than a scalar column: today the only qualifier is a
    # tier or segment reference, but audience rules grow, and growing them
    # inside JSON avoids a migration per idea.
    model.audience_filter = {"ref": broadcast.audience_ref} if broadcast.audience_ref else {}
    model.scheduled_for = broadcast.send_at
    model.started_at = broadcast.started_at
    model.finished_at = broadcast.finished_at
    model.recipient_count = broadcast.recipient_count
    model.sent_count = broadcast.sent
    model.failed_count = broadcast.failed
    model.suppressed_count = broadcast.suppressed
    model.error = broadcast.error or None
    return model


def broadcast_to_row(broadcast: Broadcast) -> BroadcastModel:
    model = BroadcastModel(id=broadcast.id, created_by=broadcast.created_by)
    return broadcast_apply(model, broadcast)


# -- schedule --------------------------------------------------------------


def schedule_to_domain(model: ScheduledJobModel) -> ScheduleEntry:
    return ScheduleEntry(
        job=JobKind(model.job),
        interval_minutes=model.interval_minutes,
        last_run_at=model.last_run_at,
        enabled=model.enabled,
    )


def schedule_apply(model: ScheduledJobModel, entry: ScheduleEntry) -> ScheduledJobModel:
    model.interval_minutes = entry.interval_minutes
    model.last_run_at = entry.last_run_at
    model.enabled = entry.enabled
    return model


def schedule_to_row(entry: ScheduleEntry) -> ScheduledJobModel:
    return schedule_apply(ScheduledJobModel(job=entry.job.value), entry)


__all__ = [
    "attempt_from_json",
    "attempt_to_json",
    "broadcast_apply",
    "broadcast_to_domain",
    "broadcast_to_row",
    "earliest_send_after",
    "notification_apply",
    "notification_to_domain",
    "notification_to_row",
    "preferences_apply",
    "preferences_to_domain",
    "preferences_to_row",
    "schedule_apply",
    "schedule_to_domain",
    "schedule_to_row",
    "summarise_state",
]
