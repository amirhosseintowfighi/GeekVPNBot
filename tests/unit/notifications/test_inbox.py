"""Mini App inbox: listing, unread counts, ownership."""

from __future__ import annotations

from geekvpn.domain.notifications.events import NotificationRead
from tests.unit.notifications.fakes import USER_ID
from tests.unit.notifications.world import World


def _fill(w: World, count: int) -> None:
    for index in range(count):
        w.engine.notify(
            user_id=USER_ID,
            template_key="payment.approved",
            fields={"amount": 100000 + index, "reference": f"PAY-{index}"},
        )
        w.clock.advance(minutes=1)


def test_inbox_lists_persian_previews():
    w = World()
    _fill(w, 1)
    page = w.inbox.list_for(USER_ID)
    item = page.items[0]
    assert item.title_fa
    assert item.preview_fa
    assert item.category_fa
    assert item.unread


def test_unread_count_tracks_reads():
    w = World()
    _fill(w, 3)
    assert w.inbox.unread_count(USER_ID) == 3
    first = w.inbox.list_for(USER_ID).items[0]
    w.inbox.mark_read(first.notification_id, user_id=USER_ID)
    assert w.inbox.unread_count(USER_ID) == 2


def test_marking_read_twice_reports_no_change():
    w = World()
    _fill(w, 1)
    item = w.inbox.list_for(USER_ID).items[0]
    assert w.inbox.mark_read(item.notification_id, user_id=USER_ID) is True
    assert w.inbox.mark_read(item.notification_id, user_id=USER_ID) is False
    assert len(w.events.of_type(NotificationRead)) == 1


def test_another_user_cannot_read_someone_elses_notification():
    """Ids are opaque but guessable."""
    w = World()
    _fill(w, 1)
    item = w.inbox.list_for(USER_ID).items[0]
    assert w.inbox.mark_read(item.notification_id, user_id=USER_ID + 99) is False
    assert w.inbox.unread_count(USER_ID) == 1


def test_pagination_reports_has_more():
    w = World()
    _fill(w, 12)
    first = w.inbox.list_for(USER_ID, page=1, page_size=10)
    assert len(first.items) == 10
    assert first.has_more
    second = w.inbox.list_for(USER_ID, page=2, page_size=10)
    assert len(second.items) == 2
    assert not second.has_more


def test_unread_only_filter():
    w = World()
    _fill(w, 3)
    item = w.inbox.list_for(USER_ID).items[0]
    w.inbox.mark_read(item.notification_id, user_id=USER_ID)
    page = w.inbox.list_for(USER_ID, unread_only=True)
    assert len(page.items) == 2


def test_mark_all_read_returns_the_number_changed():
    w = World()
    _fill(w, 4)
    assert w.inbox.mark_all_read(USER_ID) == 4
    assert w.inbox.mark_all_read(USER_ID) == 0
    assert w.inbox.unread_count(USER_ID) == 0


def test_a_message_telegram_refused_is_still_in_the_inbox():
    """The reason the inbox row is written unconditionally."""
    w = World()
    w.telegram.set_raises(RuntimeError("blocked"))
    w.engine.notify(
        user_id=USER_ID,
        template_key="expiry.today",
        fields={"plan": "Geek Turbo"},
    )
    assert len(w.inbox.list_for(USER_ID).items) == 1


def test_page_number_is_floored_at_one():
    w = World()
    _fill(w, 2)
    assert len(w.inbox.list_for(USER_ID, page=0).items) == 2
