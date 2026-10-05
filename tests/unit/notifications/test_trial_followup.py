"""A message some hours after a customer took the free trial.

The trial has been used, and the customer has not bought: the moment a shop
most wants to say something. Once per customer, by the operator's words, and
never to somebody who bought in the meantime (the candidate query's job).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.notifications.trial_followup import LOOKBACK, TrialFollowUp

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


def _followup(candidates: list[int], *, delivered: set[int] | None = None):
    windows: list[tuple[datetime, datetime]] = []
    sent: list[tuple[int, str]] = []

    def find(after: datetime, before: datetime) -> list[int]:
        windows.append((after, before))
        return candidates

    def send(user_id: int, message_fa: str) -> bool:
        sent.append((user_id, message_fa))
        return delivered is None or user_id in delivered

    return TrialFollowUp(candidates=find, send=send, clock=_Clock()), windows, sent


def test_switched_off_asks_for_nobody() -> None:
    followup, windows, sent = _followup([1])

    assert followup.run(after_hours=0, message_fa="x") == 0
    assert followup.run(after_hours=6, message_fa="  ") == 0
    assert windows == [] and sent == []


def test_trial_takers_from_before_the_wait_are_sent_the_operators_words() -> None:
    followup, windows, sent = _followup([11, 22])

    count = followup.run(after_hours=6, message_fa="تست چطور بود؟")

    assert count == 2
    assert sent == [(11, "تست چطور بود؟"), (22, "تست چطور بود؟")]
    assert windows == [(NOW - timedelta(hours=6) - LOOKBACK, NOW - timedelta(hours=6))]


def test_only_messages_that_went_out_are_counted() -> None:
    """A duplicate or a muted customer is skipped by the engine, not counted."""
    followup, _, _ = _followup([11, 22], delivered={22})

    assert followup.run(after_hours=6, message_fa="x") == 1


def test_one_customer_failing_does_not_stop_the_rest() -> None:
    sent: list[int] = []

    def send(user_id: int, message_fa: str) -> bool:
        if user_id == 11:
            raise RuntimeError("blocked the bot")
        sent.append(user_id)
        return True

    followup = TrialFollowUp(candidates=lambda a, b: [11, 22], send=send, clock=_Clock())

    assert followup.run(after_hours=6, message_fa="x") == 1
    assert sent == [22]
