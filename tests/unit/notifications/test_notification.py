"""The Notification aggregate."""

from __future__ import annotations

from datetime import timedelta

from geekvpn.domain.notifications.enums import (
    DeliveryState,
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
from geekvpn.domain.notifications.message import render
from geekvpn.domain.notifications.notification import Notification
from tests.unit.notifications.fakes import EPOCH, USER_ID

BOTH = (NotificationChannel.TELEGRAM, NotificationChannel.MINIAPP)


def _make(channels=BOTH) -> Notification:
    return Notification.queue(
        "ntf-1",
        user_id=USER_ID,
        message=render("expiry.soon", plan="Geek Turbo", days=3),
        channels=channels,
        now=EPOCH,
    )


def test_queueing_records_one_event():
    notification = _make()
    events = notification.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], NotificationQueued)


def test_collect_events_drains():
    notification = _make()
    notification.collect_events()
    assert notification.collect_events() == []


def test_every_channel_starts_pending():
    notification = _make()
    assert set(notification.pending_channels()) == set(BOTH)
    assert not notification.is_settled()


def test_marking_sent_records_the_channel_only():
    notification = _make()
    notification.collect_events()
    notification.mark_sent(NotificationChannel.TELEGRAM, now=EPOCH)
    assert notification.state_for(NotificationChannel.TELEGRAM) is DeliveryState.SENT
    assert notification.state_for(NotificationChannel.MINIAPP) is DeliveryState.PENDING
    assert isinstance(notification.collect_events()[0], NotificationSent)


def test_delivered_anywhere_is_true_with_one_success():
    notification = _make()
    notification.mark_suppressed(
        NotificationChannel.TELEGRAM, reason=SuppressionReason.BLOCKED, now=EPOCH
    )
    notification.mark_sent(NotificationChannel.MINIAPP, now=EPOCH)
    assert notification.is_delivered_anywhere()
    assert notification.is_settled()


def test_suppression_records_its_reason():
    notification = _make()
    notification.collect_events()
    notification.mark_suppressed(
        NotificationChannel.TELEGRAM, reason=SuppressionReason.MUTED, now=EPOCH
    )
    attempt = notification.delivery_for(NotificationChannel.TELEGRAM)
    assert attempt.reason is SuppressionReason.MUTED
    event = notification.collect_events()[0]
    assert isinstance(event, NotificationSuppressed)
    assert event.reason is SuppressionReason.MUTED


def test_failure_counts_attempts():
    notification = _make()
    notification.mark_failed(NotificationChannel.TELEGRAM, error="TimeoutError", now=EPOCH)
    notification.mark_failed(NotificationChannel.TELEGRAM, error="TimeoutError", now=EPOCH)
    attempt = notification.delivery_for(NotificationChannel.TELEGRAM)
    assert attempt.attempts == 2
    assert attempt.is_retryable()


def test_failure_stops_being_retryable_at_the_cap():
    notification = _make()
    for _ in range(3):
        notification.mark_failed(NotificationChannel.TELEGRAM, error="TimeoutError", now=EPOCH)
    assert not notification.delivery_for(NotificationChannel.TELEGRAM).is_retryable()


def test_suppressed_delivery_is_never_retried():
    notification = _make()
    notification.mark_suppressed(
        NotificationChannel.TELEGRAM, reason=SuppressionReason.MUTED, now=EPOCH
    )
    assert not notification.delivery_for(NotificationChannel.TELEGRAM).is_retryable()


def test_failed_event_carries_the_attempt_count():
    notification = _make()
    notification.collect_events()
    notification.mark_failed(NotificationChannel.TELEGRAM, error="Boom", now=EPOCH)
    event = notification.collect_events()[0]
    assert isinstance(event, NotificationFailed)
    assert event.attempts == 1


def test_deferring_sets_a_send_after_and_is_not_terminal():
    notification = _make()
    notification.collect_events()
    later = EPOCH + timedelta(hours=5)
    notification.defer(NotificationChannel.TELEGRAM, send_after=later, now=EPOCH)
    attempt = notification.delivery_for(NotificationChannel.TELEGRAM)
    assert attempt.state is DeliveryState.DEFERRED
    assert attempt.send_after == later
    assert not notification.is_settled()
    assert isinstance(notification.collect_events()[0], NotificationDeferred)


def test_deferred_channel_is_not_due_before_its_time():
    notification = _make(channels=(NotificationChannel.TELEGRAM,))
    later = EPOCH + timedelta(hours=5)
    notification.defer(NotificationChannel.TELEGRAM, send_after=later, now=EPOCH)
    assert notification.due_channels(EPOCH) == ()
    assert notification.due_channels(later) == (NotificationChannel.TELEGRAM,)


def test_sending_after_a_defer_clears_the_send_after():
    notification = _make(channels=(NotificationChannel.TELEGRAM,))
    notification.defer(
        NotificationChannel.TELEGRAM,
        send_after=EPOCH + timedelta(hours=5),
        now=EPOCH,
    )
    notification.mark_sent(NotificationChannel.TELEGRAM, now=EPOCH)
    attempt = notification.delivery_for(NotificationChannel.TELEGRAM)
    assert attempt.send_after is None
    assert attempt.reason is None


def test_marking_read_is_idempotent():
    """The Mini App calls this on every inbox open."""
    notification = _make()
    notification.collect_events()
    assert notification.mark_read(now=EPOCH) is True
    assert notification.mark_read(now=EPOCH + timedelta(hours=1)) is False
    events = notification.collect_events()
    assert len(events) == 1
    assert isinstance(events[0], NotificationRead)


def test_read_at_keeps_the_first_timestamp():
    notification = _make()
    notification.mark_read(now=EPOCH)
    notification.mark_read(now=EPOCH + timedelta(hours=1))
    assert notification.read_at == EPOCH


def test_new_notification_is_unread():
    assert _make().is_unread()


def test_category_comes_from_the_message():
    notification = _make()
    assert notification.category is notification.message.category
