"""A notification that could not reach Telegram is sent again, not given up on.

From the server in Iran every message to Telegram goes through a proxy, and the
connection through it sometimes times out. Each notification was tried once:
one `ConnectTimeout` and the purchase message carrying a customer's link was
filed as failed, delivered only to the Mini App inbox nobody had open. Of the
ten most recent deliveries in production, five went that way.

Two layers now. The sender retries a connection that was never made, which is
safe because Telegram cannot have received a message it was never sent. What
still fails is put back on the queue and the worker tries it again minutes
later, a few times, before it is recorded as failed.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from geekvpn.application.notifications.ports import ChannelResult
from geekvpn.domain.notifications.enums import DeliveryState, NotificationChannel
from geekvpn.domain.notifications.notification import MAX_ATTEMPTS
from geekvpn.infrastructure.notifications import telegram
from geekvpn.infrastructure.notifications.telegram import HttpTelegramSender
from tests.unit.notifications.world import World

pytestmark = pytest.mark.unit

TELEGRAM = NotificationChannel.TELEGRAM


def _deliver_link(w: World):
    return w.engine.notify(
        user_id=42, template_key="purchase.delivered", fields={"link": "https://x/sub/t"}
    )


# -- the queue ---------------------------------------------------------------


def test_a_transport_failure_is_queued_for_another_try() -> None:
    w = World()
    w.telegram.set_result(ChannelResult.broke("ConnectTimeout"))

    result = _deliver_link(w)

    attempt = w.only().delivery_for(TELEGRAM)
    assert result.outcomes[TELEGRAM] is DeliveryState.DEFERRED
    assert attempt.attempts == 1
    assert attempt.error == "ConnectTimeout"
    assert attempt.send_after is not None and attempt.send_after > w.clock.now()


def test_the_worker_sends_it_once_telegram_answers_again() -> None:
    w = World()
    w.telegram.set_result(ChannelResult.broke("ConnectTimeout"))
    _deliver_link(w)

    w.telegram.set_result(ChannelResult.sent())
    w.clock.advance(minutes=30)
    w.engine.flush_deferred()

    assert w.only().delivery_for(TELEGRAM).state is DeliveryState.SENT
    assert len(w.telegram.calls) == 2


def test_it_is_not_retried_before_its_time() -> None:
    w = World()
    w.telegram.set_result(ChannelResult.broke("ConnectTimeout"))
    _deliver_link(w)

    assert w.engine.flush_deferred() == []
    assert len(w.telegram.calls) == 1


def test_it_is_recorded_as_failed_once_the_attempts_run_out() -> None:
    w = World()
    w.telegram.set_result(ChannelResult.broke("ConnectTimeout"))
    _deliver_link(w)

    for _ in range(MAX_ATTEMPTS + 2):
        w.clock.advance(hours=3)
        w.engine.flush_deferred()

    attempt = w.only().delivery_for(TELEGRAM)
    assert attempt.state is DeliveryState.FAILED
    assert attempt.attempts == MAX_ATTEMPTS
    assert len(w.telegram.calls) == MAX_ATTEMPTS


def test_each_retry_waits_longer_than_the_last() -> None:
    w = World()
    w.telegram.set_result(ChannelResult.broke("ConnectTimeout"))
    _deliver_link(w)

    waits: list[timedelta] = []
    for _ in range(MAX_ATTEMPTS - 1):
        attempt = w.only().delivery_for(TELEGRAM)
        assert attempt.send_after is not None
        waits.append(attempt.send_after - w.clock.now())
        w.clock.set(attempt.send_after)
        w.engine.flush_deferred()

    assert waits == sorted(waits) and len(set(waits)) == len(waits)


# -- the sender --------------------------------------------------------------


def _sender(monkeypatch: pytest.MonkeyPatch, outcomes: list[object]) -> list[int]:
    calls: list[int] = []

    def fake_post(url: str, **_: object) -> httpx.Response:
        calls.append(1)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, httpx.Response)
        return outcome

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(telegram, "_pause", lambda seconds: None)
    return calls


def test_the_sender_reconnects_after_a_connection_that_timed_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _sender(
        monkeypatch,
        [httpx.ConnectTimeout("proxy"), httpx.ConnectError("proxy"), httpx.Response(200)],
    )

    HttpTelegramSender("t").send_message(chat_id=1, text="x")

    assert len(calls) == 3


def test_the_sender_gives_up_after_its_reconnects(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _sender(monkeypatch, [httpx.ConnectTimeout("proxy")] * 3)

    with pytest.raises(httpx.ConnectTimeout):
        HttpTelegramSender("t").send_message(chat_id=1, text="x")

    assert len(calls) == 3


def test_a_timeout_after_sending_is_not_resent_on_the_spot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telegram may have the message already; sending again could deliver it twice."""
    calls = _sender(monkeypatch, [httpx.ReadTimeout("slow"), httpx.Response(200)])

    with pytest.raises(httpx.ReadTimeout):
        HttpTelegramSender("t").send_message(chat_id=1, text="x")

    assert len(calls) == 1
