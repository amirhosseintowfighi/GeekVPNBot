"""Credit for a newcomer who joined and has not bought yet.

Somebody who started the bot a day ago and bought nothing is the cheapest
customer to win: they already chose this shop once. The gift is a nudge, so it
goes once per person, only after the operator's wait, and never to anyone who
bought in the meantime (the candidate query's job, not this service's).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from geekvpn.application.payments.newcomer_gift import (
    LOOKBACK,
    REFERENCE,
    NewcomerGift,
)
from geekvpn.domain.catalog.money import Money

pytestmark = pytest.mark.unit

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


class _Clock:
    def now(self) -> datetime:
        return NOW


class _Wallets:
    def __init__(self) -> None:
        self.credited: list[tuple[int, Money, str]] = []

    def credit_reward(self, *, user_id: int, amount: Money, reference: str, **_: object) -> None:
        self.credited.append((user_id, amount, reference))


def _gift(candidates: list[int], *, fail_for: int | None = None):
    wallets = _Wallets()
    windows: list[tuple[datetime, datetime]] = []
    told: list[tuple[int, int, str]] = []

    def find(joined_after: datetime, joined_before: datetime) -> list[int]:
        windows.append((joined_after, joined_before))
        return candidates

    def notify(user_id: int, amount: int, message_fa: str) -> None:
        if user_id == fail_for:
            raise RuntimeError("blocked the bot")
        told.append((user_id, amount, message_fa))

    gift = NewcomerGift(
        wallets=wallets,  # type: ignore[arg-type]
        candidates=find,
        notify=notify,
        clock=_Clock(),
    )
    return gift, wallets, windows, told


def test_switched_off_gives_nothing_and_asks_nothing() -> None:
    gift, wallets, windows, _ = _gift([1, 2])

    assert gift.run(after_hours=0, amount_toman=20_000, message_fa="x") == []
    assert gift.run(after_hours=24, amount_toman=0, message_fa="x") == []
    assert wallets.credited == [] and windows == []


def test_each_candidate_is_credited_once_under_one_reference() -> None:
    gift, wallets, _, _ = _gift([11, 22])

    given = gift.run(after_hours=24, amount_toman=20_000, message_fa="x")

    assert given == [11, 22]
    assert wallets.credited == [(11, Money(20_000), REFERENCE), (22, Money(20_000), REFERENCE)]


def test_only_people_who_joined_before_the_wait_and_lately_are_asked_for() -> None:
    gift, _, windows, _ = _gift([])

    gift.run(after_hours=24, amount_toman=20_000, message_fa="x")

    # Bounded below as well: switching it on must not pay every member the
    # shop has ever had.
    assert windows == [(NOW - timedelta(hours=24) - LOOKBACK, NOW - timedelta(hours=24))]


def test_the_customer_is_told_with_the_operators_words() -> None:
    gift, _, _, told = _gift([11])

    gift.run(after_hours=24, amount_toman=20_000, message_fa="یه هدیه برات داریم")

    assert told == [(11, 20_000, "یه هدیه برات داریم")]


def test_a_customer_who_cannot_be_told_still_keeps_the_credit() -> None:
    gift, wallets, _, _ = _gift([11, 22], fail_for=11)

    given = gift.run(after_hours=24, amount_toman=20_000, message_fa="x")

    assert given == [11, 22]
    assert len(wallets.credited) == 2
