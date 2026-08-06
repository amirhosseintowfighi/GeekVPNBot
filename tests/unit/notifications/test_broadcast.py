"""The Broadcast aggregate's state machine."""

from __future__ import annotations

from datetime import timedelta

import pytest

from geekvpn.domain.notifications.broadcast import Broadcast
from geekvpn.domain.notifications.enums import AudienceKind, BroadcastState
from geekvpn.domain.notifications.errors import (
    BroadcastNotEditable,
    IllegalBroadcastTransition,
    NotificationError,
)
from geekvpn.domain.notifications.events import (
    BroadcastCancelled,
    BroadcastCompleted,
    BroadcastScheduled,
)
from tests.unit.notifications.fakes import ADMIN_ID, EPOCH

TITLE = "\u062e\u0628\u0631 \u062a\u0627\u0632\u0647"
BODY = "\u0633\u0631\u0648\u0631\u0647\u0627\u06cc \u062c\u062f\u06cc\u062f \u0627\u0636\u0627\u0641\u0647 \u0634\u062f\u0646\u062f."


def _draft() -> Broadcast:
    return Broadcast.draft(
        "bc-1",
        title_fa=TITLE,
        body_fa=BODY,
        audience=AudienceKind.ALL,
        created_by=ADMIN_ID,
        now=EPOCH,
    )


def test_a_new_broadcast_is_an_editable_draft():
    broadcast = _draft()
    assert broadcast.state is BroadcastState.DRAFT
    assert broadcast.state.is_editable()


def test_a_short_title_is_rejected():
    with pytest.raises(NotificationError):
        Broadcast.draft(
            "bc-1",
            title_fa="a",
            body_fa=BODY,
            audience=AudienceKind.ALL,
            created_by=ADMIN_ID,
            now=EPOCH,
        )


def test_a_short_body_is_rejected():
    with pytest.raises(NotificationError):
        Broadcast.draft(
            "bc-1",
            title_fa=TITLE,
            body_fa="kk",
            audience=AudienceKind.ALL,
            created_by=ADMIN_ID,
            now=EPOCH,
        )


def test_scheduling_records_the_event():
    broadcast = _draft()
    broadcast.collect_events()
    broadcast.schedule(send_at=EPOCH + timedelta(hours=2), now=EPOCH)
    assert broadcast.state is BroadcastState.SCHEDULED
    assert isinstance(broadcast.collect_events()[0], BroadcastScheduled)


def test_scheduling_in_the_past_is_rejected():
    broadcast = _draft()
    with pytest.raises(NotificationError):
        broadcast.schedule(send_at=EPOCH - timedelta(hours=1), now=EPOCH)


def test_a_scheduled_broadcast_is_due_at_its_time():
    broadcast = _draft()
    when = EPOCH + timedelta(hours=2)
    broadcast.schedule(send_at=when, now=EPOCH)
    assert not broadcast.is_due(EPOCH)
    assert broadcast.is_due(when)


def test_a_draft_is_never_due():
    assert not _draft().is_due(EPOCH + timedelta(days=5))


def test_a_scheduled_broadcast_can_still_be_edited():
    broadcast = _draft()
    broadcast.schedule(send_at=EPOCH + timedelta(hours=2), now=EPOCH)
    broadcast.edit(title_fa="\u0639\u0646\u0648\u0627\u0646 \u062f\u06cc\u06af\u0631")
    assert broadcast.title_fa == "\u0639\u0646\u0648\u0627\u0646 \u062f\u06cc\u06af\u0631"


def test_editing_a_sending_broadcast_is_refused():
    """Half the audience already has the old copy."""
    broadcast = _draft()
    broadcast.start(recipient_count=10, now=EPOCH)
    with pytest.raises(BroadcastNotEditable):
        broadcast.edit(title_fa="\u062f\u06cc\u06af\u0631\u06cc")


def test_starting_twice_is_an_illegal_transition():
    broadcast = _draft()
    broadcast.start(recipient_count=10, now=EPOCH)
    with pytest.raises(IllegalBroadcastTransition):
        broadcast.start(recipient_count=10, now=EPOCH)


def test_progress_is_reported_as_a_percentage():
    broadcast = _draft()
    broadcast.start(recipient_count=10, now=EPOCH)
    broadcast.record_batch(sent=3, suppressed=1, failed=1)
    assert broadcast.processed() == 5
    assert broadcast.progress_percent() == 50


def test_progress_never_exceeds_one_hundred():
    broadcast = _draft()
    broadcast.start(recipient_count=2, now=EPOCH)
    broadcast.record_batch(sent=5)
    assert broadcast.progress_percent() == 100


def test_an_empty_broadcast_reads_as_complete_once_finished():
    """Zero recipients must not divide by zero."""
    broadcast = _draft()
    broadcast.start(recipient_count=0, now=EPOCH)
    assert broadcast.progress_percent() == 0
    broadcast.complete(now=EPOCH)
    assert broadcast.progress_percent() == 100


def test_completion_is_terminal_and_eventful():
    broadcast = _draft()
    broadcast.start(recipient_count=2, now=EPOCH)
    broadcast.collect_events()
    broadcast.record_batch(sent=2)
    broadcast.complete(now=EPOCH)
    assert broadcast.state is BroadcastState.SENT
    assert broadcast.state.is_terminal()
    assert isinstance(broadcast.collect_events()[0], BroadcastCompleted)


def test_a_cancelled_broadcast_still_accepts_the_in_flight_batch():
    """The worker is mid-loop when the operator hits cancel."""
    broadcast = _draft()
    broadcast.start(recipient_count=100, now=EPOCH)
    broadcast.cancel(cancelled_by=ADMIN_ID, now=EPOCH)
    broadcast.record_batch(sent=25)
    assert broadcast.state is BroadcastState.CANCELLED
    assert broadcast.sent == 25


def test_cancelling_a_sent_broadcast_is_refused():
    broadcast = _draft()
    broadcast.start(recipient_count=1, now=EPOCH)
    broadcast.complete(now=EPOCH)
    with pytest.raises(IllegalBroadcastTransition):
        broadcast.cancel(cancelled_by=ADMIN_ID, now=EPOCH)


def test_cancellation_records_who_did_it():
    broadcast = _draft()
    broadcast.collect_events()
    broadcast.cancel(cancelled_by=ADMIN_ID, now=EPOCH)
    event = broadcast.collect_events()[0]
    assert isinstance(event, BroadcastCancelled)
    assert event.cancelled_by == ADMIN_ID


def test_failing_records_the_reason():
    broadcast = _draft()
    broadcast.start(recipient_count=5, now=EPOCH)
    broadcast.fail(error="PanelUnreachable", now=EPOCH)
    assert broadcast.state is BroadcastState.FAILED
    assert broadcast.error == "PanelUnreachable"


def test_a_finished_broadcast_cannot_fail():
    broadcast = _draft()
    broadcast.start(recipient_count=1, now=EPOCH)
    broadcast.complete(now=EPOCH)
    with pytest.raises(IllegalBroadcastTransition):
        broadcast.fail(error="TooLate", now=EPOCH)
