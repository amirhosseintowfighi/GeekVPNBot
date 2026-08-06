"""Composing and sending admin broadcasts."""

from __future__ import annotations

from datetime import timedelta

import pytest

from geekvpn.domain.notifications.enums import (
    AudienceKind,
    BroadcastState,
    NotificationCategory,
)
from geekvpn.domain.notifications.errors import EmptyAudience
from geekvpn.domain.notifications.preferences import NotificationPreferences
from tests.unit.notifications.fakes import ADMIN_ID, EPOCH, QUIET_EPOCH, USER_ID
from tests.unit.notifications.world import World

TITLE = "\u0633\u0631\u0648\u0631 \u062c\u062f\u06cc\u062f"
BODY = (
    "\u0633\u0631\u0648\u0631 \u0622\u0644\u0645\u0627\u0646 \u0641\u0639\u0627\u0644 \u0634\u062f."
)


def _create(w: World):
    return w.broadcasts.create(
        title_fa=TITLE,
        body_fa=BODY,
        audience=AudienceKind.ALL,
        created_by=ADMIN_ID,
    )


def test_creating_stores_a_draft():
    w = World()
    broadcast = _create(w)
    assert w.broadcast_repo.get(broadcast.id).state is BroadcastState.DRAFT


def test_preview_shows_the_admin_copy_verbatim():
    """Admin text is passed through, not run through the catalogue."""
    w = World()
    broadcast = _create(w)
    message = w.broadcasts.preview(broadcast.id)
    assert message.title_fa == TITLE
    assert message.body_fa == BODY


def test_audience_size_asks_the_resolver():
    w = World()
    w.audience.ids = [1, 2, 3]
    broadcast = _create(w)
    assert w.broadcasts.audience_size(broadcast.id) == 3
    assert w.audience.calls[-1] == (AudienceKind.ALL, None)


def test_sending_reaches_everyone_once():
    w = World()
    w.audience.ids = [1, 2, 3, 4, 5]
    broadcast = _create(w)
    progress = w.broadcasts.send_now(broadcast.id)
    assert progress.state is BroadcastState.SENT
    assert progress.sent == 5
    assert progress.remaining == 0
    assert len(w.stored()) == 5


def test_sending_is_batched():
    w = World(batch_size=2)
    w.audience.ids = list(range(1, 6))
    broadcast = _create(w)
    progress = w.broadcasts.send_now(broadcast.id)
    assert progress.sent == 5
    assert progress.finished


def test_an_empty_audience_is_refused_rather_than_marked_sent():
    w = World()
    w.audience.ids = []
    broadcast = _create(w)
    with pytest.raises(EmptyAudience):
        w.broadcasts.send_now(broadcast.id)
    assert w.broadcast_repo.get(broadcast.id).state is BroadcastState.DRAFT


def test_a_cancel_mid_send_stops_the_remaining_batches():
    """The aggregate is re-read between batches for exactly this."""
    w = World(batch_size=2)
    w.audience.ids = list(range(1, 21))
    broadcast = _create(w)

    original_deliver = w.miniapp.deliver
    state = {"count": 0}

    def deliver(**kwargs):
        state["count"] += 1
        if state["count"] == 3:
            w.broadcasts.cancel(broadcast.id, cancelled_by=ADMIN_ID)
        return original_deliver(**kwargs)

    w.miniapp.deliver = deliver

    progress = w.broadcasts.send_now(broadcast.id)
    assert progress.state is BroadcastState.CANCELLED
    assert progress.sent < 20
    assert progress.remaining > 0


def test_a_muted_recipient_counts_as_suppressed_not_sent():
    w = World()
    w.audience.ids = [USER_ID, USER_ID + 1]
    w.set_preferences(NotificationPreferences(news=False), user_id=USER_ID)
    w.set_preferences(NotificationPreferences(news=True), user_id=USER_ID + 1)
    broadcast = _create(w)
    progress = w.broadcasts.send_now(broadcast.id)
    assert progress.sent == 1
    assert progress.suppressed == 1


def test_a_deferred_recipient_counts_as_sent():
    """Quiet hours delay a broadcast; they do not fail it."""
    w = World(now=QUIET_EPOCH)
    w.audience.ids = [USER_ID]
    broadcast = _create(w)
    progress = w.broadcasts.send_now(broadcast.id)
    assert progress.sent == 1
    assert progress.failed == 0


def test_resending_the_same_broadcast_does_not_double_message():
    w = World()
    w.audience.ids = [USER_ID]
    broadcast = _create(w)
    w.broadcasts.send_now(broadcast.id)
    assert len(w.stored()) == 1


def test_a_news_broadcast_respects_the_news_switch():
    w = World()
    w.audience.ids = [USER_ID]
    w.mute("news")
    broadcast = _create(w)
    progress = w.broadcasts.send_now(broadcast.id)
    assert progress.sent == 0
    assert progress.suppressed == 1


def test_a_critical_broadcast_reaches_muted_users():
    """For \u0642\u0637\u0639\u06cc \u0633\u0631\u0648\u0631 notices, which are not marketing."""
    w = World()
    w.audience.ids = [USER_ID]
    w.mute("news")
    broadcast = w.broadcasts.create(
        title_fa=TITLE,
        body_fa=BODY,
        audience=AudienceKind.ALL,
        created_by=ADMIN_ID,
        category=NotificationCategory.CRITICAL,
    )
    assert w.broadcasts.send_now(broadcast.id).sent == 1


def test_dispatch_due_sends_only_what_is_due():
    w = World()
    w.audience.ids = [USER_ID]
    ready = _create(w)
    later = _create(w)
    w.broadcasts.schedule(ready.id, send_at=EPOCH + timedelta(hours=1))
    w.broadcasts.schedule(later.id, send_at=EPOCH + timedelta(days=2))

    assert w.broadcasts.dispatch_due() == []

    w.clock.advance(hours=2)
    results = w.broadcasts.dispatch_due()
    assert len(results) == 1
    assert results[0].broadcast_id == ready.id


def test_one_broken_broadcast_does_not_strand_the_others():
    w = World()
    broken = _create(w)
    healthy = _create(w)
    w.broadcasts.schedule(broken.id, send_at=EPOCH + timedelta(hours=1))
    w.broadcasts.schedule(healthy.id, send_at=EPOCH + timedelta(hours=1))
    w.clock.advance(hours=2)

    def resolve(audience, *, reference=None):
        if not getattr(resolve, "called", False):
            resolve.called = True
            raise RuntimeError("segment query timed out")
        return [USER_ID]

    w.audience.resolve = resolve

    results = w.broadcasts.dispatch_due()
    assert len(results) == 2
    states = {r.state for r in results}
    assert BroadcastState.FAILED in states
    assert BroadcastState.SENT in states


def test_editing_a_draft_changes_the_preview():
    w = World()
    broadcast = _create(w)
    w.broadcasts.edit(
        broadcast.id, body_fa="\u0645\u062a\u0646 \u062a\u0627\u0632\u0647\u0654 \u062a\u0633\u062a"
    )
    assert "\u062a\u0627\u0632\u0647" in w.broadcasts.preview(broadcast.id).body_fa
