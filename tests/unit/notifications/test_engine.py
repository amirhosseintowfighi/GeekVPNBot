"""The engine's four rules: preferences, quiet hours, the inbox, isolation."""

from __future__ import annotations

from geekvpn.application.notifications.ports import ChannelResult
from geekvpn.domain.notifications.enums import (
    DeliveryState,
    NotificationChannel,
    SuppressionReason,
)
from geekvpn.domain.notifications.events import NotificationSent
from geekvpn.domain.notifications.message import render
from geekvpn.domain.notifications.preferences import NotificationPreferences, QuietHours
from tests.unit.notifications.fakes import QUIET_EPOCH, USER_ID
from tests.unit.notifications.world import World


def test_default_dispatch_reaches_both_channels():
    w = World()
    result = w.notify()
    assert result.delivered
    assert result.outcomes[NotificationChannel.TELEGRAM] is DeliveryState.SENT
    assert result.outcomes[NotificationChannel.MINIAPP] is DeliveryState.SENT


def test_dispatch_persists_the_notification():
    w = World()
    result = w.notify()
    assert w.repo.get(result.notification_id) is not None


def test_muted_category_is_never_queued():
    w = World()
    w.mute("expiry")
    result = w.notify()
    assert not result.was_queued
    assert result.skipped is SuppressionReason.MUTED
    assert w.telegram.calls == []
    assert w.stored() == []


def test_critical_ignores_a_fully_muted_user():
    """A rejected payment reaches the customer whatever they switched off."""
    w = World()
    w.set_preferences(
        NotificationPreferences(expiry=False, traffic=False, promos=False, news=False)
    )
    result = w.engine.notify(
        user_id=USER_ID,
        template_key="payment.rejected",
        fields={"reference": "PAY-1", "reason": "\u0645\u0628\u0644\u063a \u06a9\u0645"},
    )
    assert result.delivered


def test_quiet_hours_defer_telegram_but_not_the_inbox():
    """Rule 3: a pull surface wakes nobody, so the inbox is always written."""
    w = World(now=QUIET_EPOCH)
    result = w.notify()
    assert result.outcomes[NotificationChannel.TELEGRAM] is DeliveryState.DEFERRED
    assert result.outcomes[NotificationChannel.MINIAPP] is DeliveryState.SENT
    assert w.telegram.calls == []
    assert w.miniapp.calls != []


def test_critical_is_not_deferred_at_night():
    w = World(now=QUIET_EPOCH)
    result = w.engine.notify(
        user_id=USER_ID,
        template_key="expiry.expired",
        fields={"plan": "Geek Turbo"},
    )
    assert result.outcomes[NotificationChannel.TELEGRAM] is DeliveryState.SENT


def test_disabled_quiet_hours_send_immediately():
    w = World(now=QUIET_EPOCH)
    w.set_preferences(NotificationPreferences(quiet=QuietHours(enabled=False)))
    result = w.notify()
    assert result.outcomes[NotificationChannel.TELEGRAM] is DeliveryState.SENT


def test_deferred_message_is_flushed_once_the_window_passes():
    w = World(now=QUIET_EPOCH)
    w.notify()
    assert w.telegram.calls == []

    w.clock.advance(hours=8)
    flushed = w.engine.flush_deferred()
    assert len(flushed) == 1
    assert w.telegram.calls != []
    assert w.only().state_for(NotificationChannel.TELEGRAM) is DeliveryState.SENT


def test_flush_respects_a_preference_changed_overnight():
    """Muting at midnight must silence the message queued before it."""
    w = World(now=QUIET_EPOCH)
    w.notify()
    w.mute("expiry")
    w.clock.advance(hours=8)
    w.engine.flush_deferred()
    assert w.telegram.calls == []
    assert w.only().state_for(NotificationChannel.TELEGRAM) is DeliveryState.SUPPRESSED


def test_flush_does_nothing_before_the_window_ends():
    w = World(now=QUIET_EPOCH)
    w.notify()
    assert w.engine.flush_deferred() == []


def test_channel_disabled_by_preference_is_suppressed():
    w = World()
    w.mute("telegram")
    result = w.notify()
    assert result.outcomes[NotificationChannel.TELEGRAM] is DeliveryState.SUPPRESSED
    assert result.outcomes[NotificationChannel.MINIAPP] is DeliveryState.SENT


def test_a_raising_channel_does_not_stop_the_other():
    """Rule 4: Telegram exploding must not cost the customer their inbox row."""
    w = World()
    w.telegram.set_raises(RuntimeError("telegram is on fire"))
    result = w.notify()
    assert result.outcomes[NotificationChannel.TELEGRAM] is DeliveryState.FAILED
    assert result.outcomes[NotificationChannel.MINIAPP] is DeliveryState.SENT
    assert result.delivered


def test_channel_refusal_is_recorded_with_its_reason():
    w = World()
    w.telegram.set_result(ChannelResult.refused(SuppressionReason.BLOCKED))
    w.notify()
    attempt = w.only().delivery_for(NotificationChannel.TELEGRAM)
    assert attempt.state is DeliveryState.SUPPRESSED
    assert attempt.reason is SuppressionReason.BLOCKED


def test_dispatch_accepts_a_prerendered_message():
    """The path broadcast fan-out uses: render once, dispatch many."""
    w = World()
    message = render("expiry.today", plan="Geek Turbo")
    result = w.engine.dispatch(user_id=USER_ID, message=message)
    assert result.delivered
    assert w.only().message.key == "expiry.today"


def test_dedupe_key_blocks_the_second_send():
    w = World()
    first = w.engine.notify(
        user_id=USER_ID,
        template_key="expiry.soon",
        fields={"plan": "Geek Turbo", "days": 3},
        dedupe_key="expiry:sub-1:3",
    )
    second = w.engine.notify(
        user_id=USER_ID,
        template_key="expiry.soon",
        fields={"plan": "Geek Turbo", "days": 3},
        dedupe_key="expiry:sub-1:3",
    )
    assert first.was_queued
    assert not second.was_queued
    assert second.skipped is SuppressionReason.DUPLICATE
    assert len(w.stored()) == 1


def test_dedupe_is_per_user():
    w = World()
    w.engine.notify(
        user_id=USER_ID,
        template_key="expiry.today",
        fields={"plan": "Geek Turbo"},
        dedupe_key="expiry:sub-1:1",
    )
    other = w.engine.notify(
        user_id=USER_ID + 1,
        template_key="expiry.today",
        fields={"plan": "Geek Turbo"},
        dedupe_key="expiry:sub-1:1",
    )
    assert other.was_queued


def test_marketing_is_capped_per_day():
    w = World()
    for _ in range(2):
        assert w.engine.notify(
            user_id=USER_ID,
            template_key="referral.reward",
            fields={"amount": 50000},
        ).was_queued
    third = w.engine.notify(
        user_id=USER_ID,
        template_key="referral.reward",
        fields={"amount": 50000},
    )
    assert not third.was_queued
    assert third.skipped is SuppressionReason.RATE_LIMITED


def test_transactional_messages_are_never_capped():
    w = World()
    for index in range(5):
        result = w.engine.notify(
            user_id=USER_ID,
            template_key="payment.approved",
            fields={"amount": 100000, "reference": f"PAY-{index}"},
        )
        assert result.was_queued


def test_marketing_cap_expires_after_a_day():
    w = World()
    for _ in range(2):
        w.engine.notify(user_id=USER_ID, template_key="referral.reward", fields={"amount": 1000})
    w.clock.advance(days=2)
    assert w.engine.notify(
        user_id=USER_ID, template_key="referral.reward", fields={"amount": 1000}
    ).was_queued


def test_force_overrides_mute_and_quiet_hours():
    w = World(now=QUIET_EPOCH)
    w.mute("expiry")
    result = w.engine.notify(
        user_id=USER_ID,
        template_key="expiry.soon",
        fields={"plan": "Geek Turbo", "days": 3},
        force=True,
    )
    assert result.outcomes[NotificationChannel.TELEGRAM] is DeliveryState.SENT


def test_a_broken_preference_store_does_not_silence_the_system():
    """Worst case is an unwanted message, not an unnoticed expiry."""
    w = World()
    w.preferences.explode = True
    assert w.notify().delivered


def test_events_are_published_after_dispatch():
    w = World()
    w.notify()
    assert len(w.events.of_type(NotificationSent)) == 2


def test_explicit_channel_list_is_honoured():
    w = World()
    result = w.engine.notify(
        user_id=USER_ID,
        template_key="expiry.today",
        fields={"plan": "Geek Turbo"},
        channels=(NotificationChannel.MINIAPP,),
    )
    assert set(result.outcomes) == {NotificationChannel.MINIAPP}
    assert w.telegram.calls == []
