"""Category, channel and state semantics."""

from __future__ import annotations

from geekvpn.domain.notifications.enums import (
    AudienceKind,
    BroadcastState,
    DeliveryState,
    JobKind,
    NotificationCategory,
    NotificationChannel,
    SuppressionReason,
)


def test_only_critical_bypasses_quiet_hours():
    for category in NotificationCategory:
        expected = category is NotificationCategory.CRITICAL
        assert category.bypasses_quiet_hours is expected


def test_critical_has_no_preference_switch():
    assert NotificationCategory.CRITICAL.preference_key is None
    for category in NotificationCategory:
        if category is not NotificationCategory.CRITICAL:
            assert category.preference_key == category.value


def test_marketing_categories_are_promos_and_news():
    marketing = {c for c in NotificationCategory if c.is_marketing}
    assert marketing == {NotificationCategory.PROMOS, NotificationCategory.NEWS}


def test_deferred_is_not_terminal():
    assert not DeliveryState.DEFERRED.is_terminal()
    assert not DeliveryState.PENDING.is_terminal()
    assert DeliveryState.SENT.is_terminal()
    assert DeliveryState.FAILED.is_terminal()
    assert DeliveryState.SUPPRESSED.is_terminal()


def test_only_sent_counts_as_success():
    successes = [s for s in DeliveryState if s.is_success()]
    assert successes == [DeliveryState.SENT]


def test_sending_broadcast_is_no_longer_editable():
    assert BroadcastState.DRAFT.is_editable()
    assert BroadcastState.SCHEDULED.is_editable()
    assert not BroadcastState.SENDING.is_editable()
    assert not BroadcastState.SENT.is_editable()


def test_terminal_broadcast_states():
    terminal = {s for s in BroadcastState if s.is_terminal()}
    assert terminal == {
        BroadcastState.SENT,
        BroadcastState.CANCELLED,
        BroadcastState.FAILED,
    }


def test_every_label_is_persian_and_non_empty():
    """No Latin letters anywhere a customer or operator can see."""
    enums = (
        NotificationCategory,
        NotificationChannel,
        DeliveryState,
        SuppressionReason,
        BroadcastState,
        AudienceKind,
        JobKind,
    )
    for enum_cls in enums:
        for member in enum_cls:
            label = member.label_fa()
            assert label, f"{enum_cls.__name__}.{member.name} has no Persian label"
            assert not any("a" <= ch.lower() <= "z" for ch in label), (
                f"{enum_cls.__name__}.{member.name} label contains Latin: {label}"
            )
