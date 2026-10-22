""" "Check my payment": the owner asks, at most every few seconds, and hears
one of four answers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.domain.payments.enums import VerificationOutcome
from geekvpn.domain.payments.gateway import VerificationResult
from geekvpn.presentation.bot.handlers import paycheck
from geekvpn.presentation.bot.ui import text as T
from geekvpn.presentation.bot.ui.callbacks import PayCB

pytestmark = pytest.mark.unit

OWNER = 42


class _Cache:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def add_if_absent(self, key: str, _value: str, *, ttl_seconds: int) -> bool:
        if key in self.keys:
            return False
        self.keys.add(key)
        return True


def _setup(monkeypatch: pytest.MonkeyPatch, *, owner: int | None, outcome: Any = None):
    said: list[str] = []
    asked: list[str] = []

    async def toast(_query: Any, text: str = "", *, alert: bool = False) -> None:
        said.append(text)

    def verify(_container: Any, payment_id: str) -> VerificationResult:
        asked.append(payment_id)
        return VerificationResult(outcome=outcome)

    monkeypatch.setattr(paycheck, "toast", toast)
    monkeypatch.setattr(paycheck, "owner_of", lambda _c, _id: owner)
    monkeypatch.setattr(paycheck, "verify_payment", verify)
    container = SimpleNamespace(cache=_Cache())
    return container, said, asked


async def _tap(container: Any) -> None:
    await paycheck.on_check(
        SimpleNamespace(),  # type: ignore[arg-type]
        PayCB(action="check", method="-", ref="pay1"),
        container,
        user=SimpleNamespace(telegram_id=OWNER),
    )


@pytest.mark.parametrize(
    ("outcome", "answer"),
    [
        (VerificationOutcome.CONFIRMED, T.PAYCHECK_CONFIRMED),
        (VerificationOutcome.DECLINED, T.PAYCHECK_DECLINED),
        (VerificationOutcome.MISMATCH, T.PAYCHECK_REVIEW),
        (VerificationOutcome.INCONCLUSIVE, T.PAYCHECK_PENDING),
    ],
)
async def test_the_owner_hears_how_it_ended(
    monkeypatch: pytest.MonkeyPatch, outcome: Any, answer: str
) -> None:
    container, said, asked = _setup(monkeypatch, owner=OWNER, outcome=outcome)

    await _tap(container)

    assert asked == ["pay1"]
    assert said == [answer]


async def test_somebody_elses_payment_is_not_asked_about(monkeypatch: pytest.MonkeyPatch) -> None:
    container, said, asked = _setup(monkeypatch, owner=999)

    await _tap(container)

    assert asked == []
    assert said == [T.PAYCHECK_NOT_FOUND]


async def test_a_second_tap_within_the_cooldown_does_not_ask_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container, said, asked = _setup(
        monkeypatch, owner=OWNER, outcome=VerificationOutcome.INCONCLUSIVE
    )

    await _tap(container)
    await _tap(container)

    assert asked == ["pay1"]
    assert said[-1] == T.PAYCHECK_WAIT
