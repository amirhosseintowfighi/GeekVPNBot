"""The two updates a paid Stars invoice produces."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from geekvpn.domain.payments.enums import PaymentState, VerificationOutcome
from geekvpn.presentation.bot.handlers import stars
from geekvpn.presentation.bot.ui import text as T

pytestmark = pytest.mark.unit


class _Scope:
    def __init__(self, *, state: Any = None, outcome: Any = None, fails: bool = False) -> None:
        self.verified: list[str] = []
        payment = None if state is None else SimpleNamespace(state=state)

        def verify(payment_id: str) -> Any:
            self.verified.append(payment_id)
            return SimpleNamespace(outcome=outcome)

        self.sync = SimpleNamespace(
            payments=SimpleNamespace(get=lambda _id: payment),
            verification=SimpleNamespace(verify=verify),
        )
        self.fails = fails

    async def in_shop(self, work: Any) -> Any:
        if self.fails:
            raise RuntimeError("database down")
        return work(self.sync)


class _Query:
    invoice_payload = "p1"

    def __init__(self) -> None:
        self.answers: list[dict[str, Any]] = []

    async def answer(self, **kwargs: Any) -> None:
        self.answers.append(kwargs)


@pytest.mark.asyncio
async def test_an_open_payment_is_allowed_through() -> None:
    query = _Query()

    await stars.on_pre_checkout(query, scope=_Scope(state=PaymentState.PENDING_GATEWAY))  # type: ignore[arg-type]

    assert query.answers == [{"ok": True}]


@pytest.mark.asyncio
async def test_a_closed_payment_is_refused_before_any_star_moves() -> None:
    query = _Query()

    await stars.on_pre_checkout(query, scope=_Scope(state=PaymentState.EXPIRED))  # type: ignore[arg-type]

    assert query.answers == [{"ok": False, "error_message": T.STARS_PAYMENT_CLOSED}]


@pytest.mark.asyncio
async def test_a_lookup_failure_does_not_cancel_the_payment() -> None:
    """Telegram cancels after ten seconds unanswered; unknown is not closed."""
    query = _Query()

    await stars.on_pre_checkout(query, scope=_Scope(fails=True))  # type: ignore[arg-type]

    assert query.answers == [{"ok": True}]


@pytest.mark.asyncio
async def test_a_successful_payment_is_verified_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    said: list[str] = []

    async def answer(_message: Any, text: str, **_: Any) -> None:
        said.append(text)

    monkeypatch.setattr(stars, "answer", answer)
    scope = _Scope(outcome=VerificationOutcome.CONFIRMED)
    message = SimpleNamespace(
        successful_payment=SimpleNamespace(currency="XTR", invoice_payload="p1")
    )

    await stars.on_successful_payment(message, scope=scope)  # type: ignore[arg-type]

    assert scope.verified == ["p1"]
    assert said == [T.STARS_PAID]
